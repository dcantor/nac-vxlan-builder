"""Click a port on the Provision ports map, see its settings and change them."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from nacbuilder.checks import check_project
from nacbuilder.demo import build_demo
from nacbuilder.portmap import render_svg
from nacbuilder.tasks import PortSettings, clear_port, port_config, set_port, settings_of

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def demo():
    return build_demo()


def test_port_config_kinds(demo):
    shut = port_config(demo, "demo-leaf-compute3", 12)
    assert (shut.kind, shut.interface.name) == ("single", "Ethernet1/12")
    s = settings_of(shut)
    assert (s.mode, s.enabled, s.description) == ("access", False, "dev-server (shut)")
    member = port_config(demo, "demo-leaf-compute1", 1)
    assert (member.kind, member.interface.name, member.peer) == ("member", "port-channel11", "demo-leaf-compute2")
    assert settings_of(member).allowed_vlans == [2300, 2301, 2302]
    assert port_config(demo, "demo-leaf-compute1", 53).kind == "peer_link"
    assert port_config(demo, "demo-leaf-compute1", 30).kind == "unused"
    border = port_config(demo, "demo-border-external1", 48)
    assert border.kind == "single" and not border.editable  # VRF-lite routed uplink


def test_enable_a_shut_port(demo):
    s = settings_of(port_config(demo, "demo-leaf-compute3", 12))
    s.enabled = True
    q = set_port(demo, "demo-leaf-compute3", 12, s)
    assert port_config(q, "demo-leaf-compute3", 12).interface.enabled is None  # NaC default: up
    assert check_project(q) == []


def test_member_change_updates_both_vpc_peers(demo):
    s = settings_of(port_config(demo, "demo-leaf-compute1", 1))
    s.description, s.native_vlan = "esx-new", 2300
    q = set_port(demo, "demo-leaf-compute1", 1, s)
    pcs = [i for i in q.interfaces if i.name == "port-channel11" and i.switch.startswith("demo-leaf-compute")]
    assert {(i.switch, i.description, i.native_vlan) for i in pcs} == {
        ("demo-leaf-compute1", "esx-new", 2300), ("demo-leaf-compute2", "esx-new", 2300)}
    assert check_project(q) == []


def test_new_port_and_validation(demo):
    q = set_port(demo, "demo-leaf-compute1", 30, PortSettings(mode="trunk", allowed_vlans=[2301], native_vlan=2300,
                                                              speed="25gb", mtu="jumbo", edge=False))
    i = port_config(q, "demo-leaf-compute1", 30).interface
    assert (i.mode, i.trunk_allowed_vlans, i.native_vlan, i.speed, i.mtu, i.spanning_tree_portfast) == \
        ("trunk", "2300-2301", 2300, "25gb", "jumbo", None)
    with pytest.raises(ValueError, match="aren't networks"):
        set_port(demo, "demo-leaf-compute1", 30, PortSettings(mode="access", access_vlan=999))
    with pytest.raises(ValueError, match="vPC peer link"):
        set_port(demo, "demo-leaf-compute1", 53, PortSettings(access_vlan=2300))
    with pytest.raises(ValueError, match="Interfaces page"):
        set_port(demo, "demo-border-external1", 48, PortSettings(access_vlan=2300))


def test_clear_port(demo):
    q = clear_port(demo, "demo-leaf-compute1", 1)  # only member of a per-port vPC channel, on both peers
    assert port_config(q, "demo-leaf-compute2", 1).kind == "unused" and check_project(q) == []
    q = clear_port(demo, "demo-leaf-storage1", 1)  # bundled channel keeps its other port
    assert port_config(q, "demo-leaf-storage2", 2).kind == "member"
    with pytest.raises(ValueError, match="isn't in the YAML"):
        clear_port(demo, "demo-leaf-compute1", 30)


def test_svg_is_clickable_and_marks_selection(demo):
    svg, _ = render_svg(demo, ["demo-leaf-compute1"], selected=("demo-leaf-compute1", 5), clickable=True)
    assert svg.count("data-port=") == 54 and 'data-switch="demo-leaf-compute1" data-port="5"' in svg
    assert svg.count('stroke="#f08c00"') == 1


def tab(at):
    return next(t for t in at.tabs if t.label == "Provision ports")


def test_panel_preview_and_apply(demo):
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=30)
    at.session_state["project"] = demo
    at.session_state["pp_selected"] = ("demo-leaf-compute3", 12)
    at.run()
    assert not at.exception
    next(m for m in tab(at).multiselect if m.label == "Show switches").set_value(["demo-leaf-compute3"]).run()
    t = tab(at)
    assert any(m.value == "#### Ethernet1/12 on demo-leaf-compute3" for m in t.markdown)
    toggle = next(x for x in t.toggle if x.label == "Enabled (no shutdown)")
    assert toggle.value is False
    toggle.set_value(True)
    next(b for b in tab(at).button if b.label == "Preview changes").click().run()
    assert not at.exception
    assert at.session_state["task_preview"]["label"] == "Port Ethernet1/12 on demo-leaf-compute3: change access"
    next(b for b in at.button if b.label == "Apply").click().run()
    assert port_config(at.session_state["project"], "demo-leaf-compute3", 12).interface.enabled is None


def test_panel_for_peer_link_is_read_only(demo):
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=30)
    at.session_state["project"] = demo
    at.session_state["pp_selected"] = ("demo-leaf-compute1", 53)
    at.run()
    t = tab(at)
    assert any("vPC peer link to demo-leaf-compute2" in c.value for c in t.caption)
    assert not any(b.label == "Preview changes" for b in t.button)


# --- YAML diffs in the preview ---------------------------------------------------------------
def test_project_diffs(demo):
    from nacbuilder.diffing import project_diffs

    s = settings_of(port_config(demo, "demo-leaf-compute3", 12))
    s.enabled = True
    diffs = {d.name: d for d in project_diffs(demo, set_port(demo, "demo-leaf-compute3", 12, s))}
    d = diffs["topology_switches.nac.yaml"]
    assert (d.status, d.added, d.removed) == ("changed", 0, 1)
    assert "-            enabled: false" in d.diff and "Ethernet1/12" in d.diff
    assert all(x.status == "unchanged" for n, x in diffs.items() if n != "topology_switches.nac.yaml")
    assert all(x.status == "unchanged" for x in project_diffs(demo, demo))


def test_project_diffs_new_and_removed_files(demo):
    from nacbuilder.diffing import project_diffs

    no_lite = demo.model_copy(update={"vrf_lites": [], "interfaces": [i for i in demo.interfaces if i.mode == "access" or i.mode == "trunk"]})
    st = {d.name: d.status for d in project_diffs(demo, no_lite)}
    assert st["overlay_extensions.nac.yaml"] == "removed"
    assert {d.name: d.status for d in project_diffs(no_lite, demo)}["overlay_extensions.nac.yaml"] == "new"


def test_preview_shows_yaml_diff(demo):
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=30)
    at.session_state["project"] = demo
    at.session_state["pp_selected"] = ("demo-leaf-compute1", 30)
    at.run()
    t = tab(at)
    next(b for b in t.button if b.label == "Preview changes").click().run()
    assert not at.exception
    assert any(m.value == "**YAML changes**" for m in at.markdown)
    exp = next(e for e in at.expander if "topology_switches.nac.yaml" in e.label)
    assert exp.label.endswith("changed (+5 −0)")
    code = exp.code[0].value
    assert "+          - name: Ethernet1/30" in code and "+            access_vlan: 2300" in code
