"""Leaf sub-roles (compute, storage, ...)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder.cabling import build_cabling, uplink_plan_for
from nacbuilder.checks import check_project
from nacbuilder.defaults import generate_switches, group_all_leafs, groups_per_leaf_role, pair_vpc
from nacbuilder.diagram import render_svg
from nacbuilder.generate import build_documents, render_all
from nacbuilder.importer import import_texts
from nacbuilder.models import Project
from nacbuilder.sample import standard_example
from nacbuilder.tasks import new_tenant, next_leaf_names, onboard_leaf_pair

ROOT = Path(__file__).resolve().parent.parent
MODELS = {"spine": "N9K-C9364C", "border": "N9K-C93180YC-FX", "leaf": "N9K-C93180YC-FX", "leaf:storage": "N9K-C93240YC-FX2"}


def roles_fabric() -> Project:
    p = Project(leaf_roles=["compute", "storage"], role_models=MODELS)
    p.switches = generate_switches("dc1", {"compute": 4, "storage": 2}, "10.10.0.11", "10.10.0.1", 24, role_models=MODELS)
    for i, s in enumerate(p.switches):
        s.serial_number = f"FDO6000{i:04d}"
    p.vpc_peers = pair_vpc(p)
    p.attachments = group_all_leafs(p) + groups_per_leaf_role(p)
    return p


def test_generation_pairing_and_groups():
    p = roles_fabric()
    leafs = [(s.name, s.leaf_role, s.model) for s in p.switches if s.role == "leaf"]
    assert leafs[0] == ("dc1-leaf-compute1", "compute", "N9K-C93180YC-FX")
    assert leafs[-1] == ("dc1-leaf-storage2", "storage", "N9K-C93240YC-FX2")
    leaf_pairs = [(v.peer1, v.peer2) for v in p.vpc_peers if "leaf" in v.peer1]
    assert leaf_pairs == [("dc1-leaf-compute1", "dc1-leaf-compute2"), ("dc1-leaf-compute3", "dc1-leaf-compute4"),
                          ("dc1-leaf-storage1", "dc1-leaf-storage2")]
    assert set(p.attach_groups()) == {"all", "leaf-compute", "leaf-storage"}
    issues = check_project(p)
    assert [i for i in issues if i.level == "error"] == []
    assert {i.message for i in issues} <= {f"Group {g} isn't used by any VRF or network." for g in p.attach_groups()}
    assert all("leaf_role" not in s for s in build_documents(p)["topology_switches.nac.yaml"]["vxlan"]["topology"]["switches"])


def test_tenant_on_storage_leafs_only():
    p = roles_fabric()
    q = new_tenant(p, "STORAGE", [], attach_group="leaf-storage")
    vrf = q.vrfs[-1]
    assert {a.hostname for a in q.attach_groups("vrf")[vrf.vrf_attach_group]} == {"dc1-leaf-storage1", "dc1-leaf-storage2"}
    assert [i for i in check_project(q) if i.level == "error"] == []


def test_leaf_role_checks():
    p = roles_fabric()
    p.switches[4] = p.switches[4].model_copy(update={"leaf_role": "gpu"})
    p.switches[5] = p.switches[5].model_copy(update={"leaf_role": None})
    p.switches[0] = p.switches[0].model_copy(update={"leaf_role": "compute"})  # a spine
    errs = [i.message for i in check_project(p) if i.level == "error"]
    warns = [i.message for i in check_project(p) if i.level == "warning"]
    assert any("leaf role gpu isn't defined" in m for m in errs)
    assert any("only leafs have leaf roles" in m for m in errs)
    assert any("has no leaf role (compute, storage)" in m for m in warns)
    assert any("peers have different leaf roles (gpu, none)" in m for m in warns)
    off = roles_fabric().model_copy(update={"leaf_roles": []})
    assert any("no leaf roles are defined" in i.message for i in check_project(off))


def test_onboarding_storage_pair():
    p = roles_fabric()
    assert next_leaf_names(p, leaf_role="storage") == ("dc1-leaf-storage3", "dc1-leaf-storage4")
    assert next_leaf_names(p, leaf_role="compute") == ("dc1-leaf-compute5", "dc1-leaf-compute6")
    q = onboard_leaf_pair(p, next_leaf_names(p, leaf_role="storage"), model="N9K-C93240YC-FX2", leaf_role="storage",
                          groups=["leaf-storage"])
    new = [s for s in q.switches if s.name.startswith("dc1-leaf-storage3")][0]
    assert (new.leaf_role, new.model) == ("storage", "N9K-C93240YC-FX2")
    assert q.vpc_peers[-1].peer1_peerlink_interfaces == ["Ethernet1/59", "Ethernet1/60"]
    assert [i.message for i in check_project(q) if i.section in ("Switches", "vPC") and i.level == "error"] == []


def test_diagram_labels_and_cabling_order():
    p = roles_fabric()
    svg = render_svg(p)
    assert "Compute leafs · vPC" in svg and "Storage leafs · vPC" in svg
    plan = build_cabling(p, uplink_plan_for(p))
    spine1 = [r["a_switch"] for r in plan.links if r["b_device"] == "dc1-spine1" and r["source"] == "planned"]
    assert spine1[:6] == ["dc1-leaf-compute1", "dc1-leaf-compute2", "dc1-leaf-compute3", "dc1-leaf-compute4",
                          "dc1-leaf-storage1", "dc1-leaf-storage2"]


def test_import_guesses_leaf_roles():
    res = import_texts(render_all(roles_fabric()))
    q = res.project
    assert q.leaf_roles == ["compute", "storage"]
    assert {s.name: s.leaf_role for s in q.switches if s.role == "leaf"}["dc1-leaf-storage1"] == "storage"
    assert any("Leaf roles guessed" in n for n in res.notes)


def test_switches_page_defines_leaf_roles():
    at = AppTest.from_file(str(ROOT / "views" / "switches.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    at.run()
    box = next(t for t in at.text_input if t.label.startswith("Leaf roles"))
    box.set_value("compute, storage")
    next(b for b in at.button if b.label == "Save leaf roles").click().run()
    p = at.session_state["project"]
    assert p.leaf_roles == ["compute", "storage"]
    assert {sb.label for sb in at.selectbox} >= {"Compute leafs", "Storage leafs"}  # one hardware picker per leaf role
    assert any(n.label == "Storage leafs" for n in at.number_input)  # quick generate count per role
    assert not at.exception
