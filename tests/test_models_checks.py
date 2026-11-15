import pytest
from pydantic import ValidationError

from nacbuilder.checks import check_project
from nacbuilder.defaults import generate_switches, group_all_leafs, groups_per_border_set, next_network, next_vrf, pair_vpc
from nacbuilder.models import Attachment, Fabric, GlobalIbgp, Network, Project
from nacbuilder.sample import example_project, standard_example


@pytest.mark.parametrize("asn", ["65001", "4294967295", "65000.1"])
def test_good_asn(asn):
    assert GlobalIbgp(bgp_asn=asn).bgp_asn == asn


@pytest.mark.parametrize("asn", ["0", "4294967296", "65536.1", "AS65001", "650 01"])
def test_bad_asn(asn):
    with pytest.raises(ValidationError):
        GlobalIbgp(bgp_asn=asn)


def test_mac_is_lowercased_for_schema():
    assert GlobalIbgp(bgp_asn="1", anycast_gateway_mac="2020.0000.00AA").anycast_gateway_mac == "2020.0000.00aa"
    with pytest.raises(ValidationError):
        GlobalIbgp(bgp_asn="1", anycast_gateway_mac="20:20:00:00:00")


def test_fabric_name_rules():
    with pytest.raises(ValidationError):
        Fabric(name="1fabric")


def test_ports():
    assert Attachment(group="g", hostname="h", ports="Ethernet1/1, eth1/2 po10").ports == ["Ethernet1/1", "eth1/2", "po10"]
    with pytest.raises(ValidationError):
        Attachment(group="g", hostname="h", ports="Gi0/1")


def test_gateway_must_be_host_address():
    with pytest.raises(ValidationError):
        Network(name="n", net_id=1, vlan_id=10, gw_ip_address="10.0.0.0/24")


def messages(p):
    return [i.message for i in check_project(p) if i.level == "error"]


def test_standard_example_is_clean():
    assert check_project(standard_example()) == []


def test_cisco_example_breaks_only_the_design_standard():
    errs = messages(example_project())
    assert errs and all(m.startswith("Standard:") for m in errs), errs
    assert any("4 route reflectors required, found 2" in m for m in errs)
    assert any("exactly 4 spines" in m for m in errs)


def test_standard_requires_ospf_and_four_rrs():
    p = standard_example()
    p.ibgp.route_reflectors = 2
    p.underlay.general.routing_protocol = "is-is"
    errs = " | ".join(messages(p))
    assert "4 route reflectors required, found 2" in errs
    assert "underlay must be OSPF" in errs


def test_standard_requires_four_spines():
    p = standard_example()
    p.switches = [s for s in p.switches if s.name != "dc1-spine4"]
    assert any("exactly 4 spines" in m and "found 3" in m for m in messages(p))
    p = standard_example()
    p.switches[0].role = "border_spine"
    assert any("dc1-spine1 must have role spine" in m for m in messages(p))


def test_standard_requires_three_border_pairs():
    p = standard_example()
    p.switches = [s for s in p.switches if s.name != "dc1-border-external2"]
    assert any("external border set needs 2 switches, found 1" in m for m in messages(p))

    p = standard_example()
    p.switches[-1].border_set = None  # border with no set
    assert any("must be in a border set" in m for m in messages(p))

    p = standard_example()
    p.switches[4].border_set = "client"  # a leaf in a border set
    errs = " | ".join(messages(p))
    assert "its role must be border" in errs
    assert "client border set needs 2 switches, found 3" in errs


def test_reference_and_duplicate_errors():
    p = example_project()
    p.networks.append(Network(name="NaC-Net01", vrf_name="nope", net_id=150001, vlan_id=2001, network_attach_group="ghost"))
    errs = " | ".join(messages(p))
    assert "Duplicate network name NaC-Net01" in errs
    assert "VRF nope, which doesn't exist" in errs
    assert "attach group ghost, which doesn't exist" in errs
    assert "VLAN 2001 is used by both" in errs
    assert "VNI 150001 is used by both" in errs


def test_underlay_range_overlap():
    p = example_project()
    p.underlay.ipv4.underlay_vtep_loopback_ip_range = "10.0.0.0/24"
    assert any("overlaps" in m for m in messages(p))


def test_generate_switches_follows_standard():
    sw = generate_switches("dc1", 2, "192.0.2.11", "192.0.2.1", 24)
    assert [(s.name, s.role, s.border_set) for s in sw] == [
        ("dc1-spine1", "spine", None),
        ("dc1-spine2", "spine", None),
        ("dc1-spine3", "spine", None),
        ("dc1-spine4", "spine", None),
        ("dc1-leaf1", "leaf", None),
        ("dc1-leaf2", "leaf", None),
        ("dc1-border-client1", "border", "client"),
        ("dc1-border-client2", "border", "client"),
        ("dc1-border-internal1", "border", "internal"),
        ("dc1-border-internal2", "border", "internal"),
        ("dc1-border-external1", "border", "external"),
        ("dc1-border-external2", "border", "external"),
    ]
    assert str(sw[-1].management.management_ipv4_address) == "192.0.2.22"


def test_border_groups_and_all_group_exclude_borders():
    p = standard_example()
    assert {a.hostname for a in group_all_leafs(p)} == {f"dc1-leaf{i}" for i in range(1, 5)}
    groups = {}
    for a in groups_per_border_set(p):
        groups.setdefault(a.group, []).append(a.hostname)
    assert groups == {
        "border-client": ["dc1-border-client1", "dc1-border-client2"],
        "border-internal": ["dc1-border-internal1", "dc1-border-internal2"],
        "border-external": ["dc1-border-external1", "dc1-border-external2"],
    }


def test_defaults_build_a_clean_fabric():
    p = Project(switches=generate_switches("dc1", 4, "192.0.2.11", "192.0.2.1", 24))
    p.vpc_peers = pair_vpc(p, fabric_peering=True)
    p.attachments = group_all_leafs(p)
    p.vrfs = [next_vrf(p)]
    p.vrfs.append(next_vrf(p))
    p.networks = [next_network(p)]
    p.networks.append(next_network(p))
    for i, s in enumerate(p.switches):
        s.serial_number = f"FDO{i:04d}"
    assert [s.name for s in p.switches][:5] == ["dc1-spine1", "dc1-spine2", "dc1-spine3", "dc1-spine4", "dc1-leaf1"]
    assert [(v.vrf_id, v.vlan_id, v.vrf_attach_group) for v in p.vrfs] == [(50001, 2000, "all"), (50002, 2001, "all")]
    assert [(n.net_id, n.vlan_id, n.vrf_name) for n in p.networks] == [(30001, 2300, "VRF01"), (30002, 2301, "VRF01")]
    assert check_project(p) == []


def test_project_json_round_trip():
    p = example_project()
    assert Project.model_validate_json(p.model_dump_json()) == p
