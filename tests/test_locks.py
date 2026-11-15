"""Settings a developer sets in a design standard are shown grayed out on the build pages."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import standards as std
from nacbuilder.checks import check_project
from nacbuilder.sample import standard_example
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


def lock(key="dc", *names, **defaults):
    s = std.get(key)
    std.save({**std.STANDARDS, key: std.replace(s, locked=tuple(names), defaults=defaults or None)})


def run(page, p):
    at = AppTest.from_file(str(ROOT / "views" / page), default_timeout=30)
    at.session_state["project"] = p
    at.run()
    assert not at.exception
    return at


def widget(at, kind, label):
    return next(w for w in getattr(at, kind) if w.label == label)


def test_builtin_locks_and_round_trip():
    assert std.get("dc").locked == ("anycast_gateway_mac", "overlay_mode", "replication_mode", "subnet_mask")
    lock("dc", "bgp_asn", "leaf_roles", "bogus")
    assert std.get("dc").locked == ("bgp_asn", "leaf_roles")  # unknown names dropped


def test_fabric_page_grays_out_locked_and_constraints():
    lock("dc", "bgp_asn", "overlay_mode", bgp_asn="65010")
    at = run("fabric.py", standard_example())
    assert widget(at, "text_input", "BGP ASN").disabled and widget(at, "text_input", "BGP ASN").value == "65010"
    assert widget(at, "selectbox", "Overlay mode").disabled
    assert not widget(at, "text_input", "Anycast gateway MAC").disabled  # no longer locked
    assert widget(at, "text_input", "Fabric type").disabled and widget(at, "text_input", "Route reflectors").disabled


def test_unlocked_constraint_becomes_selectable():
    std.save({**std.STANDARDS, "dc": std.replace(std.get("dc"), route_reflectors=None, locked=())})
    at = run("fabric.py", standard_example())
    rr = widget(at, "selectbox", "Route reflectors")
    assert not rr.disabled and rr.options == ["2", "4"]
    assert not widget(at, "text_input", "BGP ASN").disabled


def test_underlay_page_locks():
    lock("dc", "replication_mode", "subnet_mask", "fabric_link_range", replication_mode="ingress",
         fabric_link_range="10.99.0.0/16")
    at = run("underlay.py", standard_example())
    assert widget(at, "selectbox", "BUM replication").disabled and widget(at, "selectbox", "BUM replication").value == "ingress"
    assert widget(at, "selectbox", "Fabric link mask").disabled
    assert widget(at, "text_input", "Fabric link subnet range").value == "10.99.0.0/16"
    assert widget(at, "text_input", "Fabric link subnet range").disabled
    assert not widget(at, "text_input", "VTEP loopback range").disabled
    assert widget(at, "text_input", "Routing protocol").disabled  # constraint
    next(b for b in at.button if b.label == "Save").click().run()
    u = at.session_state["project"].underlay
    assert (u.general.replication_mode, str(u.ipv4.underlay_subnet_ip_range)) == ("ingress", "10.99.0.0/16")


def test_switches_page_locks_models_roles_and_leaf_roles():
    lock("dc", "role_models", "leaf_roles", role_models={"leaf": "N9K-C93180YC-FX3"}, leaf_roles=["compute"])
    p = std.apply_locks(full_fabric())
    at = run("switches.py", p)
    assert widget(at, "selectbox", "Compute leafs").disabled
    assert not widget(at, "selectbox", "Spine").disabled
    assert widget(at, "text_input", "Leaf roles (comma separated; blank = none)").disabled
    std.save({**std.STANDARDS, "non_vxlan": std.STANDARDS["non_vxlan"]})
    assert std.get("non_vxlan").roles == ("core_router", "edge_router")


def test_mismatches_are_errors_and_apply_fixes_them():
    lock("dc", "bgp_asn", "overlay_mode", "role_models", bgp_asn="65010", role_models={"spine": "N9K-C9332D-GX2B"})
    p = full_fabric()
    errs = [i for i in check_project(p) if i.level == "error" and i.message.startswith("Standard:")]
    assert any("BGP ASN is locked to 65010, found 65001" in i.message and i.section == "Fabric" for i in errs)
    assert any("Hardware model of dc1-spine1 is locked to N9K-C9332D-GX2B, found N9K-C9364C" in i.message
               and i.section == "Switches" for i in errs)
    q = std.apply_locks(p)
    assert std.lock_mismatches(q) == []
    assert q.ibgp.bgp_asn == "65010" and all(s.model == "N9K-C9332D-GX2B" for s in q.switches if s.role == "spine")
    at = run("fabric.py", p)
    assert "doesn't follow values its design standard locks" in at.error[0].value
    next(b for b in at.button if b.label == "Apply locked values").click().run()
    assert std.lock_mismatches(at.session_state["project"]) == []


def test_new_fabric_follows_locks():
    lock("dmz", "bgp_asn", bgp_asn="65300")
    p = std.new_project("dmz")
    assert std.lock_mismatches(p) == []


def test_editor_saves_locks():
    at = AppTest.from_file(str(ROOT / "views" / "standards_editor.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    at.run()
    at.checkbox(key="std_unlock").check().run()
    at.multiselect(key="lock_dmz").set_value(["bgp_asn", "leaf_roles"])
    next(b for b in at.tabs[1].button if b.label == "Save standard").click().run()
    assert not at.exception
    assert std.get("dmz").locked == ("bgp_asn", "leaf_roles")
