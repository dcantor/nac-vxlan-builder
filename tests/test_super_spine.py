"""Optional super spine layer for DC Fabrics (2 or 4 super spines; they are the route reflectors)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from nacbuilder.cabling import build_cabling, uplink_plan_for
from nacbuilder.checks import check_project
from nacbuilder.defaults import generate_switches, group_all_leafs, next_network, next_vrf, pair_vpc
from nacbuilder.diagram import render_svg
from nacbuilder.generate import build_documents, render_all
from nacbuilder.importer import import_texts
from nacbuilder.models import Project
from nacbuilder.sample import standard_example
from nacbuilder.validate import nac_validate

ROOT = Path(__file__).resolve().parent.parent


def super_fabric(n: int = 2) -> Project:
    p = Project(super_spines=n)
    p.ibgp = p.ibgp.model_copy(update={"route_reflectors": n})
    p.switches = generate_switches("dc2", 4, "10.50.0.11", "10.50.0.1", 24, super_spines=n)
    for i, s in enumerate(p.switches):
        s.serial_number = f"FDO5000{i:04d}"
    p.vpc_peers = pair_vpc(p, peerlink_ports=["Ethernet1/53", "Ethernet1/54"])
    p.attachments = group_all_leafs(p)
    p.vrfs = [next_vrf(p)]
    p.networks = [next_network(p)]
    return p


def errors(p):
    return [i.message for i in check_project(p) if i.level == "error"]


def test_generate_with_super_spines():
    sw = generate_switches("dc2", 2, super_spines=4)
    assert [(s.name, s.role) for s in sw[:6]] == [
        ("dc2-superspine1", "super_spine"), ("dc2-superspine2", "super_spine"), ("dc2-superspine3", "super_spine"),
        ("dc2-superspine4", "super_spine"), ("dc2-spine1", "spine"), ("dc2-spine2", "spine")]


@pytest.mark.parametrize("n", [2, 4])
def test_super_spine_fabric_is_clean_and_validates(n):
    p = super_fabric(n)
    assert check_project(p) == []
    ibgp = build_documents(p)["global.nac.yaml"]["vxlan"]["global"]["ibgp"]
    assert ibgp["route_reflectors"] == n
    res = nac_validate(p)
    assert res.ok and res.strict, res.output


def test_super_spine_checks():
    p = super_fabric(2)
    p.ibgp = p.ibgp.model_copy(update={"route_reflectors": 4})
    assert any("2 super spines are the route reflectors" in m for m in errors(p))
    p = super_fabric(2)
    p.switches = [s for s in p.switches if s.name != "dc2-superspine2"]
    assert any("super spine layer needs 2 super spines" in m and "found 1" in m for m in errors(p))
    # still exactly 4 plain spines
    p = super_fabric(4)
    p.switches = [s for s in p.switches if s.name != "dc2-spine4"]
    assert any("exactly 4 spines required, found 3" in m for m in errors(p))


def test_super_spines_need_the_option_and_dc():
    p = super_fabric(2).model_copy(update={"super_spines": None})
    p.ibgp = p.ibgp.model_copy(update={"route_reflectors": 4})
    assert any("turn on the super spine layer on the Fabric page" in m for m in errors(p))
    dmz = super_fabric(2).model_copy(update={"standard": "dmz"})
    assert not dmz.has_super_spines
    assert any("a DMZ Fabric has no super spine layer" in m for m in errors(dmz))


def test_diagram_marks_super_spines_as_route_reflectors():
    svg = render_svg(super_fabric(2))
    assert svg.count("super_spine · RR") == 2
    assert "spine · RR" not in svg.replace("super_spine · RR", "")
    assert 'stroke="#6366f1"' in svg  # super spine to spine links


def test_cabling_plans_super_spine_links():
    p = super_fabric(2)
    plan = build_cabling(p, uplink_plan_for(p))
    assert plan.conflicts == []
    sup = [r for r in plan.links if r["type"] == "super spine link (planned)"]
    assert len(sup) == 4 * 2
    assert sup[0] == {"type": "super spine link (planned)", "a_switch": "dc2-spine1", "a_port": "Ethernet1/61",
                      "b_device": "dc2-superspine1", "b_port": "Ethernet1/1",
                      "detail": "spine to super spine; ND discovers it", "source": "planned"}
    fabric = [r for r in plan.links if r["type"] == "fabric link (planned)"]
    assert {r["b_device"] for r in fabric} == {"dc2-spine1", "dc2-spine2", "dc2-spine3", "dc2-spine4"}  # leafs -> spines only


def test_import_turns_the_layer_on():
    res = import_texts(render_all(super_fabric(4)))
    assert res.errors == [] and res.project.super_spines == 4
    assert check_project(res.project) == []
    assert any("super spine layer is turned on" in n for n in res.notes)


def test_fabric_page_toggle():
    at = AppTest.from_file(str(ROOT / "views" / "fabric.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    at.run()
    toggle = next(t for t in at.toggle if t.label == "Add a super spine layer")
    toggle.set_value(True).run()
    next(r for r in at.radio if r.label == "Super spines").set_value(4).run()
    assert any("adding a layer of 4 super spines" in w.value for w in at.warning)
    next(b for b in at.button if b.label == "Save").click().run()
    p = at.session_state["project"]
    assert (p.super_spines, p.ibgp.route_reflectors) == (4, 4)
    # DMZ has no option
    at.radio[0].set_value("dmz").run()
    assert not any(t.label == "Add a super spine layer" for t in at.toggle)
    assert not at.exception


def test_super_spines_sit_on_their_own_row_above_the_spines():
    import re

    svg = render_svg(super_fabric(2))
    ys = {}
    for name in ("dc2-superspine1", "dc2-spine1", "dc2-leaf1"):
        m = re.search(rf"<g><title>{name} .*?<rect x=\"[\d.]+\" y=\"([\d.]+)\"", svg)
        ys[name] = float(m[1])
    assert ys["dc2-superspine1"] < ys["dc2-spine1"] < ys["dc2-leaf1"]
