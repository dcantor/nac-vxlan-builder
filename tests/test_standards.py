"""DC Fabric, DMZ Fabric and Non-VXLAN design (NaC External fabric)."""

from pathlib import Path

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from nacbuilder import standards as std
from nacbuilder.checks import check_project
from nacbuilder.defaults import generate_external_switches, pair_vpc, vpc_port_channel
from nacbuilder.diagram import render_svg
from nacbuilder.generate import build_documents, render_all
from nacbuilder.importer import import_texts
from nacbuilder.models import Fabric, Interface, Project
from nacbuilder.sample import standard_example
from nacbuilder.validate import nac_validate

ROOT = Path(__file__).resolve().parent.parent


def external_fabric() -> Project:
    p = Project(fabric=Fabric(name="ext1", type="External"), standard="non_vxlan")
    p.ibgp = p.ibgp.model_copy(update={"bgp_asn": "65100"})
    p.switches = generate_external_switches("ext1", 2, 2, "10.30.0.11", "10.30.0.1", 24)
    for i, s in enumerate(p.switches):
        s.serial_number = f"FDO3000000{i}"
    p.vpc_peers = pair_vpc(p, peerlink_ports=["Ethernet1/53", "Ethernet1/54"])
    edge = next(v for v in p.vpc_peers if v.peer1 == "ext1-edge1")
    p.interfaces = vpc_port_channel(edge, 20, 20, ["Ethernet1/1"], ["Ethernet1/1"], "trunk", trunk_vlans="100-110",
                                    description="fw-01")
    p.interfaces.append(Interface(switch="ext1-core1", name="Ethernet1/1", mode="routed", ipv4_address="10.40.0.1/31",
                                  description="WAN"))
    return p


def test_standards_catalog():
    assert [s.label for s in std.STANDARDS.values()] == ["DC Fabric", "DMZ Fabric", "Non-VXLAN design"]
    dc, dmz, ext = std.get("dc"), std.get("dmz"), std.get("non_vxlan")
    rules = ("fabric_type", "vxlan", "underlay_protocol", "spine_count", "route_reflectors", "border_sets", "borders_per_set")
    assert all(getattr(dc, r) == getattr(dmz, r) for r in rules), "DMZ uses the DC rules"
    assert (ext.fabric_type, ext.vxlan) == ("External", False)
    assert std.get(None).key == "dc" and std.for_fabric_type("External") == "non_vxlan"


def test_dmz_follows_dc_rules():
    p = standard_example().model_copy(update={"standard": "dmz"})
    assert check_project(p) == []
    p.switches = [s for s in p.switches if s.name != "dc1-spine4"]
    assert any("exactly 4 spines" in i.message for i in check_project(p))


def test_external_fabric_yaml_and_validation():
    p = external_fabric()
    assert check_project(p) == []
    docs = build_documents(p)
    assert list(docs) == ["global.nac.yaml", "topology_switches.nac.yaml"]
    assert docs["global.nac.yaml"] == {"vxlan": {"fabric": {"name": "ext1", "type": "External"},
                                                 "global": {"external": {"bgp_asn": "65100"}}}}
    topo = docs["topology_switches.nac.yaml"]["vxlan"]["topology"]
    assert [s["role"] for s in topo["switches"]] == ["core_router", "core_router", "edge_router", "edge_router"]
    assert [(v["peer1"], v["peer2"]) for v in topo["vpc_peers"]] == [("ext1-core1", "ext1-core2"), ("ext1-edge1", "ext1-edge2")]
    res = nac_validate(p)
    assert res.ok and res.strict, res.output


def test_external_fabric_checks():
    p = external_fabric()
    p.switches[0] = p.switches[0].model_copy(update={"role": "leaf"})
    p.vrfs = standard_example().vrfs
    msgs = [i.message for i in check_project(p) if i.level == "error"]
    assert any("ext1-core1 is a leaf" in m for m in msgs)
    assert any("has no VRFs, so 1 VRF(s) won't be written" in m for m in msgs)
    # no VXLAN-only noise (spines, underlay, attach groups) for an External fabric
    assert not any("spine" in m or "Underlay" in m for m in msgs)
    assert "vrfs.nac.yaml" not in render_all(p)


def test_switching_standard_changes_output_only():
    p = standard_example()
    q = p.model_copy(update={"standard": "non_vxlan"})
    assert list(build_documents(q)) == ["global.nac.yaml", "topology_switches.nac.yaml"]
    assert build_documents(q)["global.nac.yaml"]["vxlan"]["fabric"]["type"] == "External"
    back = q.model_copy(update={"standard": "dc"})
    assert build_documents(back) == build_documents(p)  # nothing was lost by switching back


def test_import_external_fabric():
    files = render_all(external_fabric())
    res = import_texts(files)
    assert res.errors == [], res.errors
    q = res.project
    assert q.standard == "non_vxlan" and q.ibgp.bgp_asn == "65100"
    assert {k: yaml.safe_load(v) for k, v in render_all(q).items()} == {k: yaml.safe_load(v) for k, v in files.items()}
    assert any("Non-VXLAN design" in n for n in res.notes)
    dc = import_texts(render_all(standard_example()))
    assert dc.project.standard == "dc" and any("DMZ" in n for n in dc.notes)


def test_diagram_for_external_fabric():
    svg = render_svg(external_fabric())
    assert "Non-VXLAN design · External fabric · AS 65100" in svg
    assert "· RR" not in svg


def test_fabric_page_switches_standard():
    at = AppTest.from_file(str(ROOT / "views" / "fabric.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    at.run()
    assert [o for o in at.radio[0].options] == ["DC Fabric", "DMZ Fabric", "Non-VXLAN design"]
    at.radio[0].set_value("non_vxlan").run()
    assert any("Not saved yet" in w.value and "1 VRF(s)" in w.value for w in at.warning)
    assert not any(t.label == "Anycast gateway MAC" for t in at.text_input)  # VXLAN-only fields hidden
    next(b for b in at.button if b.label == "Save").click().run()
    p = at.session_state["project"]
    assert (p.standard, p.fabric.type) == ("non_vxlan", "External")
    assert not at.exception


@pytest.mark.parametrize("standard, hidden", [("dc", []), ("non_vxlan", ["VRFs", "Networks", "Underlay", "VRF-lite"])])
def test_tasks_page_per_standard(standard, hidden):
    p = standard_example() if standard == "dc" else external_fabric()
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=30)
    at.session_state["project"] = p
    at.run()
    labels = [t.label for t in at.tabs]
    assert not at.exception
    assert labels == (["Decommission"] if standard == "non_vxlan" else
                      ["New tenant", "Add VRF", "Add VLAN", "Extend to switches", "Provision ports", "Onboard a leaf pair",
                       "Decommission"])
