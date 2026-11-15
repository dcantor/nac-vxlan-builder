"""Sample fabrics.

- `example_project()`: Cisco's ansible-dc-vxlan-example (tag 0.9.1) fabric, used as the
  golden reference for YAML output. It does NOT follow our design standard (2 spines).
- `standard_example()`: a small fabric that follows standards.py, offered in the UI.
"""

from .models import (
    Attachment,
    Fabric,
    GlobalIbgp,
    Management,
    ManagementServer,
    Network,
    Project,
    Switch,
    Underlay,
    UnderlayGeneral,
    UnderlayIpv4,
    UnderlayMulticast,
    UnderlayOspf,
    Vrf,
)

_SWITCHES = [
    ("netascode-spine1", "99H2TUPCVFK", "spine", "10.1.1.21"),
    ("netascode-spine2", "941L30Q8ZYI", "spine", "10.1.1.22"),
    ("netascode-leaf1", "9LWGEUPJOCM", "leaf", "10.1.1.11"),
    ("netascode-leaf2", "9YEXD0OHA7Z", "leaf", "10.1.1.12"),
    ("netascode-leaf3", "9M2TXMZ7D3N", "leaf", "10.1.1.13"),
    ("netascode-leaf4", "982YGMKUY2B", "leaf", "10.1.1.14"),
]
_LEAFS = [s[0] for s in _SWITCHES if s[2] == "leaf"]


def example_project() -> Project:
    ports = ["Ethernet1/13", "Ethernet1/14"]
    return Project(
        fabric=Fabric(name="nac-fabric1", type="VXLAN_EVPN"),
        ibgp=GlobalIbgp(
            greenfield_cleanup="Enable",
            bgp_asn="65001",
            route_reflectors=2,
            anycast_gateway_mac="12:34:56:78:90:00",
            dns_servers=[ManagementServer(ip_address="10.0.0.2")],
            ntp_servers=[ManagementServer(ip_address="10.55.0.2")],
        ),
        switches=[
            Switch(
                name=n,
                serial_number=sn,
                role=r,
                management=Management(default_gateway_v4="10.1.1.1", management_ipv4_address=ip),
            )
            for n, sn, r, ip in _SWITCHES
        ],
        underlay=Underlay(
            general=UnderlayGeneral(routing_protocol="ospf", replication_mode="multicast"),
            ipv4=UnderlayIpv4(
                subnet_mask=31,
                underlay_routing_loopback_ip_range="10.0.0.0/22",
                underlay_vtep_loopback_ip_range="10.100.100.0/22",
                underlay_rp_loopback_ip_range="10.250.250.0/24",
                underlay_subnet_ip_range="10.1.0.0/16",
            ),
            ospf=UnderlayOspf(area_id="0.0.0.0"),
            multicast=UnderlayMulticast(underlay_rp_loopback_id=250, underlay_primary_rp_loopback_id=0),
        ),
        vrfs=[
            Vrf(name="NaC-VRF01", vrf_id=150001, vlan_id=2001, vrf_attach_group="all"),
            Vrf(name="NaC-VRF02", vrf_id=150002, vlan_id=2002, vrf_attach_group="leaf1"),
            Vrf(name="NaC-VRF03", vrf_id=150003, vlan_id=2003, vrf_attach_group="leaf2"),
        ],
        networks=[
            Network(name="NaC-Net01", vrf_name="NaC-VRF01", net_id=130001, vlan_id=2301,
                    vlan_name="NaC-Net01_vlan2301", gw_ip_address="192.168.12.1/24", network_attach_group="all"),
            Network(name="NaC-Net02", vrf_name="NaC-VRF02", net_id=130002, vlan_id=2302,
                    vlan_name="NaC-Net02_vlan2302", gw_ip_address="192.168.12.2/24", network_attach_group="leaf1"),
            Network(name="NaC-Net03", vrf_name="NaC-VRF03", net_id=130003, vlan_id=2303,
                    vlan_name="NaC-Net03_vlan2303", gw_ip_address="192.168.12.3/24", gw_ipv6_address="2001::1/64",
                    route_target_both=True, l3gw_on_border=True, mtu_l3intf=9000,
                    int_desc="Configured by NetAsCode", network_attach_group="leaf2"),
        ],
        attachments=[
            # VRF group "all" has all four leafs; network group "all" only leaf1/leaf2 (with ports).
            *[Attachment(group="all", hostname=h, ports=ports, used_for="both") for h in _LEAFS[:2]],
            *[Attachment(group="all", hostname=h, used_for="vrf") for h in _LEAFS[2:]],
            *[Attachment(group=f"leaf{i}", hostname=h) for i, h in enumerate(_LEAFS, 1)],
        ],
    )


def standard_example() -> Project:
    """4 spines (all RRs), 4 leafs, client/internal/external border pairs, OSPF underlay."""
    from . import hardware as hw
    from .defaults import generate_switches, group_all_leafs, next_network, next_vrf, pair_vpc

    switches = generate_switches("dc1", 4, "10.10.0.11", "10.10.0.1", 24, role_models=hw.suggested())
    for i, s in enumerate(switches, 1):
        s.serial_number = f"FDO24{i:05d}"
    p = Project(
        fabric=Fabric(name="dc1", type="VXLAN_EVPN"),
        ibgp=GlobalIbgp(
            bgp_asn="65001",
            route_reflectors=4,
            overlay_mode="cli",
            dns_servers=[ManagementServer(ip_address="10.10.0.53")],
            ntp_servers=[ManagementServer(ip_address="10.10.0.123")],
        ),
        switches=switches,
        underlay=Underlay(multicast=UnderlayMulticast(rendezvous_points=4)),
    )
    p.vpc_peers = pair_vpc(p, peerlink_ports=["Ethernet1/53", "Ethernet1/54"])
    p.attachments = group_all_leafs(p, ports=["Ethernet1/10"])
    p.vrfs = [next_vrf(p)]
    net = next_network(p)
    net.gw_ip_address = "172.16.10.1/24"
    p.networks = [net]
    return p
