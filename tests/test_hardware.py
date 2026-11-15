"""Nexus 9300 hardware catalog: port layouts, model-based numbering and port checks."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import hardware as hw
from nacbuilder.cabling import build_cabling, uplink_plan_for
from nacbuilder.checks import check_project
from nacbuilder.defaults import generate_switches, pair_vpc, vrf_lite_uplink
from nacbuilder.generate import build_documents
from nacbuilder.importer import import_texts
from nacbuilder.models import Interface, Project
from nacbuilder.sample import standard_example
from nacbuilder.tasks import onboard_leaf_pair

ROOT = Path(__file__).resolve().parent.parent


def msgs(p, level="error"):
    return [i.message for i in check_project(p) if i.level == level]


def test_catalog_is_consistent():
    cat = hw.catalog()
    assert len(cat) >= 15
    for name, m in cat.items():
        ports = set(m.numbers())
        assert set(m.host) <= ports and set(m.uplink) <= ports and set(m.spine) <= ports, name
        assert m.roles and m.groups, name
        if "leaf" in m.roles or "border" in m.roles:
            assert m.host and len(m.uplink) >= 6, f"{name}: 4 spine uplinks + 2-port peer link"
        if "spine" in m.roles:
            assert m.spine, name
    for role, model in hw.suggested().items():
        assert model in cat and cat[model].offered_for(role), (role, model)


def test_ports_and_breakouts():
    m = hw.get("N9K-C93180YC-FX")
    assert m.has_port("Ethernet1/54") and m.has_port("eth1/1") and not m.has_port("Ethernet1/55")
    assert m.has_port("Ethernet1/49/2") and not m.has_port("Ethernet1/10/1")  # breakout only on 40G+
    assert m.speed("Ethernet1/12") == "25G" and m.speed("Ethernet1/50") == "100G"
    assert m.peer_link() == ["Ethernet1/53", "Ethernet1/54"]
    assert hw.get("N9K-C93240YC-FX2").peer_link() == ["Ethernet1/59", "Ethernet1/60"]
    assert hw.get("N9K-C9364C").super_uplinks(2) == ["Ethernet1/63", "Ethernet1/64"]
    assert "N9K-C9364C" in hw.models_for("super_spine") and "N9K-C9364C" not in hw.models_for("leaf")


def test_example_fabric_uses_suggested_models_and_is_clean():
    p = standard_example()
    assert {s.role: s.model for s in p.switches} == {"spine": "N9K-C9364C", "leaf": "N9K-C93180YC-FX",
                                                       "border": "N9K-C93180YC-FX"}
    assert check_project(p) == []
    topo = build_documents(p)["topology_switches.nac.yaml"]["vxlan"]["topology"]["switches"]
    assert all("model" not in s for s in topo)  # app-only


def test_port_checks():
    p = standard_example()
    p.interfaces.append(Interface(switch="dc1-leaf1", name="Ethernet1/60", mode="access", access_vlan=10))
    p.interfaces.append(Interface(switch="dc1-leaf2", name="port-channel30", mode="trunk",
                                  members=["Ethernet1/10", "Ethernet1/50"]))
    p.vpc_peers[0] = p.vpc_peers[0].model_copy(update={"peer1_peerlink_interfaces": ["Ethernet1/70", "Ethernet1/54"]})
    errs = " | ".join(msgs(p))
    assert "dc1-leaf1 Ethernet1/60 doesn't exist on N9K-C93180YC-FX" in errs
    assert "dc1-border-client1 Ethernet1/70 doesn't exist" in errs
    warns = " | ".join(msgs(p, "warning"))
    assert "dc1-leaf2 port-channel30: members mix speeds (100G, 25G)" in warns
    p.switches[4] = p.switches[4].model_copy(update={"model": "N9K-C93240YC-FX2"})  # leaf1
    assert any("peers are different models" in m for m in msgs(p, "warning"))
    p.switches[0] = p.switches[0].model_copy(update={"model": "N9K-C93180YC-FX"})  # a leaf model on a spine
    assert any("isn't offered for the spine role" in m for m in msgs(p, "warning"))


def test_pairing_uses_each_models_peer_link():
    p = Project(switches=generate_switches("dc9", 2, role_models={"leaf": "N9K-C93240YC-FX2", "spine": "N9K-C9364C",
                                                                 "border": "N9K-C93360YC-FX2"}))
    pairs = {(v.peer1, v.peer2): (v.peer1_peerlink_interfaces, v.peer2_peerlink_interfaces) for v in pair_vpc(p)}
    assert pairs[("dc9-leaf1", "dc9-leaf2")] == (["Ethernet1/59", "Ethernet1/60"], ["Ethernet1/59", "Ethernet1/60"])
    assert pairs[("dc9-border-client1", "dc9-border-client2")][0] == ["Ethernet1/107", "Ethernet1/108"]
    assert vrf_lite_uplink(p) == "Ethernet1/96"


def test_cabling_follows_models():
    p = Project(switches=generate_switches("dc9", 2, role_models={"leaf": "N9K-C93240YC-FX2", "spine": "N9K-C9332C",
                                                                 "border": "N9K-C93180YC-FX"}))
    plan = build_cabling(p, uplink_plan_for(p).__class__(**{**uplink_plan_for(p).__dict__, "from_models": True}))
    assert plan.conflicts == []
    leaf1 = [(r["a_port"], r["b_device"], r["b_port"]) for r in plan.links if r["a_switch"] == "dc9-leaf1"]
    assert leaf1 == [("Ethernet1/49", "dc9-spine1", "Ethernet1/1"), ("Ethernet1/50", "dc9-spine2", "Ethernet1/1"),
                     ("Ethernet1/51", "dc9-spine3", "Ethernet1/1"), ("Ethernet1/52", "dc9-spine4", "Ethernet1/1")]
    assert {r["speed"] for r in plan.ports if r["switch"] == "dc9-spine1"} == {"100G"}
    # 9332C spines have 32 ports: 40 leafs + 6 borders don't fit
    big = Project(switches=generate_switches("dc9", 40, role_models={"leaf": "N9K-C93180YC-FX", "spine": "N9K-C9332C",
                                                                     "border": "N9K-C93180YC-FX"}))
    bplan = build_cabling(big, uplink_plan_for(big).__class__(**{**uplink_plan_for(big).__dict__, "from_models": True}))
    assert any("dc9-spine1 (N9K-C9332C) has no free port" in c for c in bplan.conflicts)


def test_super_spine_cabling_from_models():
    p = Project(super_spines=2, switches=generate_switches("dc9", 2, super_spines=2, role_models=hw.suggested()))
    up = uplink_plan_for(p)
    up.from_models = True
    plan = build_cabling(p, up)
    s1 = [(r["a_port"], r["b_device"], r["b_port"]) for r in plan.links
          if r["a_switch"] == "dc9-spine1" and r["type"].startswith("super")]
    assert s1 == [("Ethernet1/63", "dc9-superspine1", "Ethernet1/1"), ("Ethernet1/64", "dc9-superspine2", "Ethernet1/1")]
    assert plan.conflicts == []


def test_onboarding_with_a_model():
    p = standard_example()
    q = onboard_leaf_pair(p, ("dc1-leaf5", "dc1-leaf6"), model="N9K-C93240YC-FX2")
    pair = q.vpc_peers[-1]
    assert pair.peer1_peerlink_interfaces == ["Ethernet1/59", "Ethernet1/60"]
    assert {s.model for s in q.switches if s.name in ("dc1-leaf5", "dc1-leaf6")} == {"N9K-C93240YC-FX2"}


def test_import_reads_preprovision_model():
    text = """
vxlan:
  fabric: {name: f1, type: VXLAN_EVPN}
  global: {ibgp: {bgp_asn: "65001"}}
  topology:
    switches:
      - name: l1
        role: leaf
        poap: {preprovision: {serial_number: ABC, model: N9K-C93180YC-FX3, version: 10.4(3)}}
"""
    res = import_texts({"a.yaml": text})
    sw = res.project.switches[0]
    assert sw.model == "N9K-C93180YC-FX3"
    assert res.project.preserved.switches["l1"]["poap"]["preprovision"]["model"] == "N9K-C93180YC-FX3"


def test_switches_page_applies_models():
    p = standard_example()
    p.switches = [s.model_copy(update={"model": None}) for s in p.switches]
    at = AppTest.from_file(str(ROOT / "views" / "switches.py"), default_timeout=30)
    at.session_state["project"] = p
    at.run()
    next(sb for sb in at.selectbox if sb.label == "Leaf").set_value("N9K-C93240YC-FX2")
    next(b for b in at.button if b.label == "Apply to switches").click().run()
    q = at.session_state["project"]
    assert {s.model for s in q.switches if s.role == "leaf"} == {"N9K-C93240YC-FX2"}
    assert {s.model for s in q.switches if s.role == "spine"} == {"N9K-C9364C"}
    assert q.role_models["leaf"] == "N9K-C93240YC-FX2"
    assert not at.exception


def test_interfaces_page_shows_port_map():
    at = AppTest.from_file(str(ROOT / "views" / "interfaces.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    at.session_state["if_filter"] = "dc1-leaf1"
    at.run()
    assert any("N9K-C93180YC-FX" in c.value and "48 host ports free" in c.value for c in at.caption)
    assert not at.exception
