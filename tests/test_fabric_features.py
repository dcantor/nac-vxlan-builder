"""vPC pairs, interfaces, VRF-lite and the topology diagram."""

import pytest
import yaml
from pydantic import ValidationError

from nacbuilder.checks import check_project
from nacbuilder.defaults import apply_vrf_lite_plan, build_vrf_lite, expand_ports, pair_vpc, vpc_port_channel
from nacbuilder.diagram import render_svg
from nacbuilder.generate import build_documents, render_all
from nacbuilder.importer import import_texts
from nacbuilder.models import Interface, VpcPeer
from nacbuilder.sample import standard_example
from nacbuilder.validate import nac_validate


def errors(p, section=None):
    return [i.message for i in check_project(p) if i.level == "error" and (section is None or i.section == section)]


def full_fabric():
    """Standard example + a vPC host port-channel + a VRF-lite handoff on the external borders."""
    p = standard_example()
    leaf_pair = next(v for v in p.vpc_peers if v.peer1 == "dc1-leaf1")
    p.interfaces += vpc_port_channel(leaf_pair, 10, 10, ["Ethernet1/1"], ["Ethernet1/1"], "trunk", trunk_vlans="2300")
    p.interfaces.append(Interface(switch="dc1-leaf3", name="Ethernet1/5", mode="access", access_vlan=2300))
    plan = build_vrf_lite(p, "VRF01", {"dc1-border-external1": ["Ethernet1/49"], "dc1-border-external2": ["Ethernet1/49"]},
                          2000, "10.254.0.0/24", 30, 65500)
    return apply_vrf_lite_plan(p, plan)


@pytest.fixture
def fabric():
    return full_fabric()


def test_fabric_is_clean_and_validates(fabric):
    assert check_project(fabric) == []
    res = nac_validate(fabric)
    assert res.ok and res.strict, res.output


def test_generated_yaml(fabric):
    docs = build_documents(fabric)
    topo = docs["topology_switches.nac.yaml"]["vxlan"]["topology"]
    assert [ (v["peer1"], v["peer2"], v["domain_id"]) for v in topo["vpc_peers"]] == [
        ("dc1-border-client1", "dc1-border-client2", 1),
        ("dc1-border-internal1", "dc1-border-internal2", 2),
        ("dc1-border-external1", "dc1-border-external2", 3),
        ("dc1-leaf1", "dc1-leaf2", 4),
        ("dc1-leaf3", "dc1-leaf4", 5),
    ]
    assert topo["vpc_peers"][0]["peer1_peerlink_interfaces"] == [{"name": "Ethernet1/53"}, {"name": "Ethernet1/54"}]
    leaf1 = next(s for s in topo["switches"] if s["name"] == "dc1-leaf1")
    assert leaf1["interfaces"] == [{
        "name": "port-channel10", "mode": "trunk", "trunk_allowed_vlans": [{"from": 2300}],
        "members": ["Ethernet1/1"], "vpc_id": 10,
    }]
    ext1 = next(s for s in topo["switches"] if s["name"] == "dc1-border-external1")
    assert ext1["interfaces"] == [
        {"name": "Ethernet1/49", "mode": "routed", "description": "VRF-lite uplink"},
        {"name": "Ethernet1/49.2000", "mode": "routed_sub", "description": "VRF-lite VRF01",
         "ipv4_address": "10.254.0.1/30", "vrf": "VRF01", "dot1q_id": 2000},
    ]
    lite = docs["overlay_extensions.nac.yaml"]["vxlan"]["overlay_extensions"]["vrf_lites"][0]
    assert lite["switches"][1] == {"name": "dc1-border-external2", "interfaces": [{"name": "Ethernet1/49.2000"}],
                                   "bgp_peers": [{"address": "10.254.0.6", "remote_as": 65500}]}
    # Group "all" is shared with the networks, so VRF01 gets its own group: the leafs plus the external borders.
    vrfs = docs["vrfs.nac.yaml"]["vxlan"]["overlay"]
    assert vrfs["vrfs"][0]["vrf_attach_group"] == "VRF01-vrf"
    groups = {g["name"]: [s["hostname"] for s in g["switches"]] for g in vrfs["vrf_attach_groups"]}
    assert groups == {"VRF01-vrf": ["dc1-leaf1", "dc1-leaf2", "dc1-leaf3", "dc1-leaf4",
                                    "dc1-border-external1", "dc1-border-external2"]}
    net_group = docs["networks.nac.yaml"]["vxlan"]["overlay"]["network_attach_groups"][0]["switches"]
    assert not any(s["hostname"].startswith("dc1-border") for s in net_group)


def test_import_round_trip(fabric):
    files = render_all(fabric)
    res = import_texts(files)
    assert res.errors == [], res.errors
    q = res.project
    assert q.vpc_peers == fabric.vpc_peers
    assert sorted(i.key for i in q.interfaces) == sorted(i.key for i in fabric.interfaces)
    assert q.vrf_lites == fabric.vrf_lites
    assert q.preserved.is_empty()
    assert {k: yaml.safe_load(v) for k, v in render_all(q).items()} == {k: yaml.safe_load(v) for k, v in files.items()}


def test_import_keeps_unsupported_interfaces_and_vrf_lites():
    text = """
vxlan:
  fabric: {name: f1, type: VXLAN_EVPN}
  global: {ibgp: {bgp_asn: "65001"}}
  topology:
    switches:
      - name: b1
        role: border
        interfaces:
          - {name: Ethernet1/1, mode: dot1q, dot1q_tunnel_vlan: 10}
          - {name: Ethernet1/2, mode: access, access_vlan: 20, storm_control_action: trap}
  overlay_extensions:
    vrf_lites:
      - {name: OSPF-LITE, vrf: V1, ospf: {process: 1}, switches: [{name: b1}]}
"""
    res = import_texts({"a.yaml": text})
    assert res.errors == []
    p = res.project
    assert [i.name for i in p.interfaces] == ["Ethernet1/2"]
    assert p.preserved.interfaces == {"b1/Ethernet1/2": {"storm_control_action": "trap"}}
    out = build_documents(p)
    ifs = out["topology_switches.nac.yaml"]["vxlan"]["topology"]["switches"][0]["interfaces"]
    assert {"name": "Ethernet1/2", "mode": "access", "access_vlan": 20, "storm_control_action": "trap"} in ifs
    assert {"name": "Ethernet1/1", "mode": "dot1q", "dot1q_tunnel_vlan": 10} in ifs
    assert out["overlay_extensions.nac.yaml"]["vxlan"]["overlay_extensions"]["vrf_lites"][0]["name"] == "OSPF-LITE"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"name": "port-channel5", "mode": "trunk"}, "needs member ports"),
        ({"name": "Ethernet1/1", "mode": "access", "members": "Ethernet1/2"}, "only port-channels"),
        ({"name": "Ethernet1/1", "mode": "access", "vpc_id": 5}, "vpc_id is only"),
        ({"name": "Ethernet1/49.10", "mode": "routed_sub"}, "needs a dot1q_id"),
        ({"name": "Ethernet1/49", "mode": "routed_sub", "dot1q_id": 10}, "named like"),
        ({"name": "Ethernet1/1", "mode": "trunk", "access_vlan": 10}, "access_vlan only"),
        ({"name": "Ethernet1/1", "mode": "access", "ipv4_address": "10.0.0.1/30"}, "only apply to routed"),
        ({"name": "Ethernet1/1", "mode": "trunk", "trunk_allowed_vlans": "20-10"}, "low to high"),
        ({"name": "Gi0/1", "mode": "access"}, "Ethernet port"),
        ({"name": "Ethernet1/1", "mode": "access", "mtu": 100}, "MTU"),
    ],
)
def test_interface_validation(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        Interface(switch="l1", **kwargs)


def test_expand_ports():
    assert expand_ports("Ethernet1/1-3, e1/10 ethernet1/2/1-2") == [
        "Ethernet1/1", "Ethernet1/2", "Ethernet1/3", "e1/10", "ethernet1/2/1", "ethernet1/2/2"]
    with pytest.raises(ValueError):
        expand_ports("Ethernet1/5-2")


def test_vpc_checks(fabric):
    p = fabric.model_copy(deep=True)
    p.vpc_peers.append(VpcPeer(peer1="dc1-leaf1", peer2="dc1-spine1", domain_id=4, fabric_peering=True))
    errs = " | ".join(errors(p, "vPC"))
    assert "dc1-spine1 is a spine" in errs and "dc1-leaf1 is in two vPC pairs" in errs and "Duplicate vPC domain ID 4" in errs
    p = fabric.model_copy(deep=True)
    p.vpc_peers[0] = p.vpc_peers[0].model_copy(update={"peer2_peerlink_interfaces": []})
    assert any("set peer-link ports on both" in m for m in errors(p, "vPC"))
    p = fabric.model_copy(deep=True)
    p.vpc_peers = [v for v in p.vpc_peers if v.peer1 != "dc1-border-client1"]
    assert any("client border pair" in i.message for i in check_project(p) if i.level == "warning")


def test_interface_checks(fabric):
    p = fabric.model_copy(deep=True)
    p.interfaces = [i for i in p.interfaces if not (i.switch == "dc1-leaf2" and i.vpc_id)]
    assert any("vPC ID 10 is only on dc1-leaf1" in m for m in errors(p, "Interfaces"))
    p = fabric.model_copy(deep=True)
    p.interfaces.append(Interface(switch="dc1-leaf1", name="Ethernet1/53", mode="access"))
    p.interfaces.append(Interface(switch="dc1-leaf1", name="Ethernet1/1", mode="access"))
    p.interfaces.append(Interface(switch="dc1-leaf3", name="Ethernet1/9", mode="routed", vrf="NOPE"))
    p.interfaces.append(Interface(switch="dc1-leaf3", name="port-channel20", mode="trunk", members="Ethernet1/7", vpc_id=20))
    errs = " | ".join(errors(p, "Interfaces"))
    assert "dc1-leaf1 Ethernet1/53 is a vPC peer-link port" in errs
    assert "ethernet1/1 is configured on its own but is also a member of port-channel10" in errs
    assert "uses VRF NOPE" in errs
    assert "vPC ID 20 is only on dc1-leaf3" in errs


def test_vrf_lite_checks(fabric):
    p = fabric.model_copy(deep=True)
    p.attachments = [a for a in p.attachments if not a.hostname.startswith("dc1-border-external")]
    assert p.vrfs[0].vrf_attach_group == "VRF01-vrf"
    p.interfaces = [i for i in p.interfaces if not (i.switch == "dc1-border-external2" and i.mode == "routed_sub")]
    p.vrf_lites[0].switches[0].bgp_peers[0] = p.vrf_lites[0].switches[0].bgp_peers[0].model_copy(update={"remote_as": 65001})
    errs = " | ".join(errors(p, "VRF-lite"))
    assert "VRF VRF01 isn't attached to dc1-border-external1" in errs
    assert "dc1-border-external2 Ethernet1/49.2000 isn't defined" in errs
    assert "uses the fabric's own ASN" in errs


def test_vrf_lite_plan_allocates_free_subnets(fabric):
    plan = build_vrf_lite(fabric, "VRF01", {"dc1-border-external1": ["Ethernet1/50"]}, 3000, "10.254.0.0/24", 31,
                          65500, name="second")
    assert plan.links == [{"switch": "dc1-border-external1", "interface": "Ethernet1/50.3000",
                           "local": "10.254.0.8/31", "neighbor": "10.254.0.9"}]
    with pytest.raises(ValueError, match="no free"):
        build_vrf_lite(fabric, "VRF01", {"dc1-border-external1": ["Ethernet1/51"]}, 3001, "10.254.0.0/29", 30, 65500, "x")
    with pytest.raises(ValueError, match="already exists"):
        build_vrf_lite(fabric, "VRF01", {"dc1-border-external1": ["Ethernet1/49"]}, 2000, "10.254.1.0/24", 30, 65500, "y")


def test_diagram(fabric):
    svg = render_svg(fabric)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    for name in ("dc1-spine4", "dc1-leaf4", "dc1-border-external2", "External borders · vPC 3", "AS 65500", "spine · RR"):
        assert name in svg, name
    assert 'stroke="#dc2626"' not in svg
    # Switches named in error messages get a red outline (whole-name match: leaf1 isn't leaf10).
    p = fabric.model_copy(deep=True)
    p.interfaces = [i for i in p.interfaces if not (i.switch == "dc1-leaf2" and i.vpc_id)]
    svg = render_svg(p)
    assert svg.count('stroke="#dc2626"') == 1
    assert "dc1-leaf1 (leaf) — has check errors" in svg
