"""Developer-only Design standards editor: saving, reloading, restoring, and the effect on fabrics."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import standards as std
from nacbuilder.checks import check_project
from nacbuilder.defaults import next_network, next_vrf
from nacbuilder.sample import standard_example

ROOT = Path(__file__).resolve().parent.parent


def test_save_reload_and_restore():
    assert not std.is_customised()
    dc = std.get("dc")
    new = std.replace(dc, spine_count=2, route_reflectors=2, defaults={"bgp_asn": "65010", "l3_vni_start": 60001})
    std.save({**std.STANDARDS, "dc": new})
    assert std.is_customised()
    std.reload()
    s = std.get("dc")
    assert (s.spine_count, s.route_reflectors, s.defaults.bgp_asn, s.defaults.l3_vni_start) == (2, 2, "65010", 60001)
    assert s.border_sets == dc.border_sets and std.get("dmz") == std.BUILTIN["dmz"]  # untouched values kept
    assert std.SPINE_COUNT == 2  # module constants follow
    std.restore_builtin()
    assert not std.is_customised() and std.get("dc") == std.BUILTIN["dc"]


def test_partial_file_falls_back_to_builtin():
    std.STANDARDS_FILE.write_text("standards:\n  dc:\n    label: House DC\n    defaults:\n      bgp_asn: '65020'\n")
    std.reload()
    s = std.get("dc")
    assert (s.label, s.defaults.bgp_asn, s.spine_count) == ("House DC", "65020", 4)


def test_constraints_drive_checks():
    p = standard_example()
    assert not [i for i in check_project(p) if i.level == "error"]
    std.save({**std.STANDARDS, "dc": std.replace(std.get("dc"), spine_count=6)})
    assert any("6 spines" in i.message for i in check_project(p) if i.level == "error")
    std.save({**std.STANDARDS, "dc": std.replace(std.get("dc"), spine_count=None, route_reflectors=None,
                                                  underlay_protocol=None)})
    assert not [i for i in check_project(p) if i.level == "error"]


def test_defaults_drive_new_fabrics_and_pools():
    std.save({**std.STANDARDS, "dmz": std.replace(std.get("dmz"), defaults={
        "bgp_asn": "65200", "subnet_mask": 31, "leaf_roles": ["compute", "storage"], "vrf_vlan_start": 3000,
        "l3_vni_start": 70001, "network_vlan_start": 3300, "l2_vni_start": 40001})})
    p = std.new_project("dmz")
    assert (p.ibgp.bgp_asn, p.underlay.ipv4.subnet_mask, p.leaf_roles) == ("65200", 31, ["compute", "storage"])
    v = next_vrf(p)
    assert (v.vrf_id, v.vlan_id) == (70001, 3000)
    n = next_network(p)
    assert (n.net_id, n.vlan_id) == (40001, 3300)


def page():
    at = AppTest.from_file(str(ROOT / "views" / "standards_editor.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    return at.run()


def test_page_is_locked_until_acknowledged():
    at = page()
    assert not at.exception
    assert "For developers only" in at.error[0].value
    assert all(b.disabled for b in at.button if b.label == "Save standard")
    at.checkbox(key="std_unlock").check().run()
    assert not any(b.disabled for b in at.button if b.label == "Save standard")


def test_page_saves_and_validates():
    at = page()
    at.checkbox(key="std_unlock").check().run()
    dmz = next(t for t in at.tabs if t.label == "DMZ Fabric")
    next(t for t in dmz.text_input if t.label == "BGP ASN").set_value("not-an-asn")
    next(b for b in dmz.button if b.label == "Save standard").click().run()
    assert any("Not saved" in e.value for e in at.error) and not std.is_customised()
    dmz = next(t for t in at.tabs if t.label == "DMZ Fabric")
    next(t for t in dmz.text_input if t.label == "BGP ASN").set_value("65300")
    next(n for n in dmz.number_input if n.label == "Spines (0 = any)").set_value(0)
    next(b for b in dmz.button if b.label == "Save standard").click().run()
    assert not at.exception and std.is_customised()
    s = std.get("dmz")
    assert (s.defaults.bgp_asn, s.spine_count) == ("65300", None)
    assert std.get("dc") == std.BUILTIN["dc"]
