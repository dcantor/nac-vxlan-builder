"""Day-2 task: provision access/trunk host ports (single, port-channel, vPC) using data-model VLANs only."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from nacbuilder.checks import check_project
from nacbuilder.models import Interface
from nacbuilder.tasks import NetworkSpec, PortSpec, add_vlan, network_vlans, provision_ports
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fabric():
    """full_fabric with three VLANs (networks): 2300 NET01, 2301 APP, 2302 DB."""
    return add_vlan(full_fabric(), "VRF01", [NetworkSpec("APP", "172.16.20.1/24", vlan_id=2301),
                                             NetworkSpec("DB", "172.16.30.1/24", vlan_id=2302)])


def errors(p):
    return [i.message for i in check_project(p) if i.level == "error"]


def new_ifs(before, after):
    keys = {i.key for i in before.interfaces}
    return [i for i in after.interfaces if i.key not in keys]


def test_vlan_choices_come_from_networks(fabric):
    assert network_vlans(fabric) == {2300: "NET01", 2301: "APP", 2302: "DB"}


def test_access_single_ports(fabric):
    q = provision_ports(fabric, PortSpec("Ethernet1/20-21", "access", switches=["dc1-leaf3", "dc1-leaf4"],
                                         access_vlan=2301, description="app"))
    ifs = new_ifs(fabric, q)
    assert [(i.switch, i.name, i.mode, i.access_vlan) for i in ifs] == [
        ("dc1-leaf3", "Ethernet1/20", "access", 2301), ("dc1-leaf3", "Ethernet1/21", "access", 2301),
        ("dc1-leaf4", "Ethernet1/20", "access", 2301), ("dc1-leaf4", "Ethernet1/21", "access", 2301)]
    assert all(i.spanning_tree_portfast and i.enable_bpdu_guard and i.description == "app" for i in ifs)
    assert errors(q) == []


def test_trunk_vpc_per_port_and_bundled(fabric):
    pair = next(v for v in fabric.vpc_peers if v.peer1 == "dc1-leaf3").key
    per = provision_ports(fabric, PortSpec("Ethernet1/20-21", "trunk", vpc_pair=pair, attach="vpc",
                                           allowed_vlans=[2301, 2302], native_vlan=2300))
    ifs = new_ifs(fabric, per)
    assert [(i.switch, i.name, i.members, i.vpc_id) for i in ifs] == [
        ("dc1-leaf3", "port-channel11", ["Ethernet1/20"], 11), ("dc1-leaf4", "port-channel11", ["Ethernet1/20"], 11),
        ("dc1-leaf3", "port-channel12", ["Ethernet1/21"], 12), ("dc1-leaf4", "port-channel12", ["Ethernet1/21"], 12)]
    assert {(i.trunk_allowed_vlans, i.native_vlan) for i in ifs} == {("2300-2302", 2300)}  # native added to allowed
    assert errors(per) == []
    one = provision_ports(fabric, PortSpec("Ethernet1/20-21", "trunk", vpc_pair=pair, attach="vpc", bundle=True,
                                           allowed_vlans=[2301]))
    ifs = new_ifs(fabric, one)
    assert [(i.switch, i.name, i.members, i.vpc_id) for i in ifs] == [
        ("dc1-leaf3", "port-channel11", ["Ethernet1/20", "Ethernet1/21"], 11),
        ("dc1-leaf4", "port-channel11", ["Ethernet1/20", "Ethernet1/21"], 11)]


def test_plain_port_channel(fabric):
    q = provision_ports(fabric, PortSpec("Ethernet1/30-31", "access", switches=["dc1-leaf3"], attach="port-channel",
                                         bundle=True, access_vlan=2302))
    (pc,) = new_ifs(fabric, q)
    assert (pc.name, pc.members, pc.vpc_id, pc.access_vlan) == ("port-channel11", ["Ethernet1/30", "Ethernet1/31"], None, 2302)
    assert errors(q) == []


def test_only_data_model_vlans(fabric):
    with pytest.raises(ValueError, match="aren't networks in the data model"):
        provision_ports(fabric, PortSpec("Ethernet1/20", "access", switches=["dc1-leaf3"], access_vlan=999))
    with pytest.raises(ValueError, match="aren't networks"):
        provision_ports(fabric, PortSpec("Ethernet1/20", "trunk", switches=["dc1-leaf3"], allowed_vlans=[2301],
                                         native_vlan=4000))
    with pytest.raises(ValueError, match="pick the access VLAN"):
        provision_ports(fabric, PortSpec("Ethernet1/20", "access", switches=["dc1-leaf3"]))


def test_existing_ports_need_replace(fabric):
    spec = PortSpec("Ethernet1/1", "access", switches=["dc1-leaf1"], access_vlan=2301)
    with pytest.raises(ValueError, match="already configured: dc1-leaf1 Ethernet1/1"):
        provision_ports(fabric, spec)
    spec.replace = True
    q = provision_ports(fabric, spec)
    # Ethernet1/1 was port-channel10's only member on leaf1, so that port-channel is gone there
    assert not any(i.switch == "dc1-leaf1" and i.name == "port-channel10" for i in q.interfaces)
    assert any(i.switch == "dc1-leaf1" and i.name == "Ethernet1/1" and i.access_vlan == 2301 for i in q.interfaces)


def test_deploys_the_vlans_where_the_ports_are(fabric):
    q = provision_ports(fabric, PortSpec("Ethernet1/30", "access", switches=["dc1-border-client1"], access_vlan=2301))
    app = next(n for n in q.networks if n.name == "APP")
    assert "dc1-border-client1" in {a.hostname for a in q.attach_groups("network")[app.network_attach_group]}
    other = next(n for n in q.networks if n.name == "DB")
    assert "dc1-border-client1" not in {a.hostname for a in q.attach_groups("network")[other.network_attach_group]}
    assert errors(q) == []
    off = provision_ports(fabric, PortSpec("Ethernet1/30", "access", switches=["dc1-border-client1"], access_vlan=2301,
                                           deploy_networks=False))
    assert off.attachments == fabric.attachments


def test_check_flags_vlans_that_are_not_networks(fabric):
    fabric.interfaces.append(Interface(switch="dc1-leaf3", name="Ethernet1/40", mode="trunk",
                                       trunk_allowed_vlans="2301,2999", native_vlan=2302))
    msgs = [i.message for i in check_project(fabric) if i.level == "warning"]
    assert "dc1-leaf3 Ethernet1/40 uses VLAN(s) 2999 that aren't networks in the data model." in msgs
    assert "dc1-leaf3 Ethernet1/40: native VLAN 2302 isn't in its allowed VLANs." in msgs


def test_tab_flow(fabric):
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=30)
    at.session_state["project"] = fabric
    at.run()
    tab = at.tabs[4]
    assert tab.label == "Provision ports"
    next(r for r in tab.radio if r.label == "Interface type").set_value("trunk").run()
    tab = at.tabs[4]
    next(m for m in tab.multiselect if m.label == "Switches").set_value(["dc1-leaf3"])
    next(t for t in tab.text_input if t.label == "Ports").set_value("Ethernet1/25")
    allowed = next(m for m in tab.multiselect if m.label == "Tagged (allowed) VLANs")
    assert allowed.options == ["2300 · NET01 (VRF01)", "2301 · APP (VRF01)", "2302 · DB (VRF01)"]  # data-model VLANs only
    allowed.set_value([2301, 2302])
    next(b for b in tab.button if b.label == "Preview").click().run()
    assert not at.exception
    assert at.session_state["task_preview"]["label"].startswith("Provision trunk single ports Ethernet1/25 on dc1-leaf3")
    next(b for b in at.button if b.label == "Apply").click().run()
    port = next(i for i in at.session_state["project"].interfaces if i.switch == "dc1-leaf3" and i.name == "Ethernet1/25")
    assert (port.mode, port.trunk_allowed_vlans) == ("trunk", "2301-2302")
