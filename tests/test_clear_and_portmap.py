"""Clear fabric (Fabric page) and the port map on Day-2 → Provision ports."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import standards as std
from nacbuilder.models import Interface
from nacbuilder.portmap import COLORS, DISABLED, ENABLED, UNUSED, port_number, render_svg, switch_ports
from nacbuilder.tasks import NetworkSpec, add_vlan, clear_fabric, clear_summary
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


# --- clear fabric -------------------------------------------------------------------------
def test_clear_keeps_only_name_and_standard():
    p = full_fabric()
    p.standard = "dmz"
    q = clear_fabric(p)
    assert (q.fabric.name, q.standard) == ("dc1", "dmz")
    assert not (q.switches or q.vrfs or q.networks or q.interfaces or q.vpc_peers or q.vrf_lites or q.attachments)
    assert q.preserved.is_empty() and std.lock_mismatches(q) == []
    assert q == clear_fabric(q)
    assert clear_summary(p)[0] == "14 switch(es)" and clear_summary(q) == []


def test_clear_needs_the_fabric_name_typed():
    at = AppTest.from_file(str(ROOT / "views" / "fabric.py"), default_timeout=30)
    at.session_state["project"] = full_fabric()
    at.run()
    go = next(b for b in at.button if b.key == "clear_go")
    assert go.disabled
    at.text_input(key="clear_confirm_dc1").set_value("dc2").run()
    assert next(b for b in at.button if b.key == "clear_go").disabled
    at.text_input(key="clear_confirm_dc1").set_value("dc1").run()
    next(b for b in at.button if b.key == "clear_go").click().run()
    assert not at.exception
    q = at.session_state["project"]
    assert q.fabric.name == "dc1" and q.switches == []
    assert at.session_state["flash"] == "Cleared all settings for dc1"


# --- port map -----------------------------------------------------------------------------
def test_port_number():
    assert [port_number(x) for x in ("Ethernet1/7", "eth1/49/2", "e1/3.100", "port-channel5")] == [7, 49, 3, None]


def test_port_states():
    p = full_fabric()
    p.interfaces += [Interface(switch="dc1-leaf1", name="Ethernet1/5", mode="access", access_vlan=2300, enabled=False),
                     Interface(switch="dc1-leaf1", name="Ethernet1/6", mode="access", access_vlan=2300,
                               description="esx-01")]
    ports = {pt.number: pt for pt in switch_ports(p, "dc1-leaf1")}
    assert len(ports) == 54  # N9K-C93180YC-FX
    assert ports[1].state == ENABLED and "member of port-channel10 (vPC 10)" in ports[1].details[0]
    assert ports[5].state == DISABLED and ports[6].state == ENABLED and "'esx-01'" in ports[6].details[0]
    assert ports[53].state == ENABLED and ports[53].details == ["vPC peer link to dc1-leaf2"]
    assert ports[20].state == UNUSED


def test_disabled_port_channel_marks_members_red():
    p = full_fabric()
    p.interfaces = [i.model_copy(update={"enabled": False}) if i.name == "port-channel10" else i for i in p.interfaces]
    ports = {pt.number: pt for pt in switch_ports(p, "dc1-leaf1")}
    assert ports[1].state == DISABLED


def test_svg_colors_and_highlight():
    p = full_fabric()
    p.interfaces.append(Interface(switch="dc1-leaf1", name="Ethernet1/5", mode="access", access_vlan=2300, enabled=False))
    svg, height = render_svg(p, ["dc1-leaf1", "dc1-spine1"], {("dc1-leaf1", 5)})
    assert svg.startswith("<svg") and height > 100
    assert svg.count(COLORS[DISABLED]) == 1 and COLORS[ENABLED] in svg and COLORS[UNUSED] in svg
    assert svg.count('stroke="#1f6feb"') == 1 and "dc1-spine1 · N9K-C9364C" in svg


def test_provision_tab_shows_map_and_preview_highlights_new_ports():
    p = add_vlan(full_fabric(), "VRF01", [NetworkSpec("APP", "172.16.20.1/24", vlan_id=2301)])
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=30)
    at.session_state["project"] = p
    at.run()
    assert not at.exception
    tab = at.tabs[4]
    assert next(m for m in tab.multiselect if m.label == "Show switches").value == ["dc1-leaf1", "dc1-leaf2"]
    assert any("enabled in the YAML" in c.value for c in tab.caption)
    # preview a provision: the map after the change outlines the new port
    tab = at.tabs[4]
    next(m for m in tab.multiselect if m.label == "Switches").set_value(["dc1-leaf3"])
    next(t for t in tab.text_input if t.label == "Ports").set_value("Ethernet1/20")
    next(b for b in tab.button if b.label == "Preview").click().run()
    assert not at.exception
    assert any(m.value == "**Port map after this change**" for m in at.markdown)
    assert any("blue outline = added or changed by this preview" in c.value for c in at.caption)
