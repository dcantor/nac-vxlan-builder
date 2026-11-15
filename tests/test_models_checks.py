import pytest
from pydantic import ValidationError

from nacbuilder.checks import check_project
from nacbuilder.defaults import generate_switches, group_all_leafs, next_network, next_vrf
from nacbuilder.models import Attachment, Fabric, GlobalIbgp, Network, Project, Vrf
from nacbuilder.sample import example_project


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


def test_example_has_no_errors():
    assert messages(example_project()) == []


def test_reference_and_duplicate_errors():
    p = example_project()
    p.networks.append(Network(name="NaC-Net01", vrf_name="nope", net_id=150001, vlan_id=2001, network_attach_group="ghost"))
    errs = " | ".join(messages(p))
    assert "Duplicate network name NaC-Net01" in errs
    assert "VRF nope, which doesn't exist" in errs
    assert "attach group ghost, which doesn't exist" in errs
    assert "VLAN 2001 is used by both" in errs
    assert "VNI 150001 is used by both" in errs


def test_route_reflectors_need_spines():
    p = example_project()
    p.ibgp.route_reflectors = 4
    assert any("4 route reflectors" in m for m in messages(p))


def test_underlay_range_overlap():
    p = example_project()
    p.underlay.ipv4.underlay_vtep_loopback_ip_range = "10.0.0.0/24"
    assert any("overlaps" in m for m in messages(p))


def test_defaults_build_a_clean_fabric():
    p = Project(switches=generate_switches("dc1", 2, 4, 0, "192.0.2.11", "192.0.2.1", 24))
    p.attachments = group_all_leafs(p)
    p.vrfs = [next_vrf(p)]
    p.vrfs.append(next_vrf(p))
    p.networks = [next_network(p)]
    p.networks.append(next_network(p))
    for s, sn in zip(p.switches, "ABCDEF"):
        s.serial_number = f"FDO{sn}"
    assert [s.name for s in p.switches][:3] == ["dc1-spine1", "dc1-spine2", "dc1-leaf1"]
    assert [(v.vrf_id, v.vlan_id, v.vrf_attach_group) for v in p.vrfs] == [(50001, 2000, "all"), (50002, 2001, "all")]
    assert [(n.net_id, n.vlan_id, n.vrf_name) for n in p.networks] == [(30001, 2300, "VRF01"), (30002, 2301, "VRF01")]
    assert check_project(p) == []


def test_project_json_round_trip():
    p = example_project()
    assert Project.model_validate_json(p.model_dump_json()) == p
