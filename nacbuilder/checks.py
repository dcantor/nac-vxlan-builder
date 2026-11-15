"""Cross-section checks the schema can't express (duplicates, references, sizing)."""

from collections import Counter
from dataclasses import dataclass
from ipaddress import IPv4Interface
from itertools import combinations
from typing import Literal

from . import standards as std
from .models import ATTACHABLE_ROLES, SPINE_ROLES, Project


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    section: str
    message: str


def _dups(values) -> list:
    return sorted(v for v, n in Counter(x for x in values if x is not None).items() if n > 1)


def check_project(p: Project) -> list[Issue]:
    issues: list[Issue] = []

    def err(section, msg):
        issues.append(Issue("error", section, msg))

    def warn(section, msg):
        issues.append(Issue("warning", section, msg))

    # --- switches -------------------------------------------------------------
    sw = p.switches
    by_name = {s.name: s for s in sw}
    spines = [s for s in sw if s.role in SPINE_ROLES]
    if not sw:
        warn("Switches", "No switches defined yet.")
    else:
        if not spines:
            err("Switches", "The fabric needs at least one spine.")
        if not any(s.role in ATTACHABLE_ROLES for s in sw):
            warn("Switches", "No leaf/border switches to attach VRFs and networks to.")
    for d in _dups(s.name for s in sw):
        err("Switches", f"Duplicate switch name {d}.")
    for d in _dups(s.serial_number for s in sw):
        err("Switches", f"Duplicate serial number {d}.")
    mgmt_ips = [s.management.management_ipv4_address if s.management else None for s in sw]
    for d in _dups(mgmt_ips):
        err("Switches", f"Duplicate management IP {d}.")
    for s in sw:
        if not s.serial_number:
            warn("Switches", f"{s.name} has no serial number; Nexus Dashboard needs it to add the switch.")
        m = s.management
        if not m or not m.management_ipv4_address:
            warn("Switches", f"{s.name} has no management IPv4 address.")
            continue
        if m.default_gateway_v4 and m.subnet_mask_ipv4:
            net = IPv4Interface(f"{m.management_ipv4_address}/{m.subnet_mask_ipv4}").network
            if m.default_gateway_v4 not in net:
                warn("Switches", f"{s.name}: gateway {m.default_gateway_v4} is outside {net}.")
        if m.default_gateway_v4 == m.management_ipv4_address:
            err("Switches", f"{s.name}: management IP equals its gateway.")

    # --- design standard (standards.py) ---------------------------------------
    if p.fabric.type != std.FABRIC_TYPE:
        err("Fabric", f"Standard: the overlay must be BGP EVPN ({std.FABRIC_TYPE} with iBGP).")
    if p.ibgp.route_reflectors != std.ROUTE_REFLECTORS:
        err("Fabric", f"Standard: {std.ROUTE_REFLECTORS} route reflectors required, found {p.ibgp.route_reflectors}.")
    if p.underlay.general.routing_protocol != std.UNDERLAY_PROTOCOL:
        err("Underlay", f"Standard: the underlay must be OSPF, found {p.underlay.general.routing_protocol}.")
    if sw:
        if len(spines) != std.SPINE_COUNT:
            err(
                "Switches",
                f"Standard: exactly {std.SPINE_COUNT} spines (all route reflectors) required, found {len(spines)}.",
            )
        for s in spines:
            if s.role != "spine":
                err("Switches", f"Standard: {s.name} must have role spine, not {s.role}.")
        for key_, label in std.BORDER_SETS.items():
            members = [s.name for s in sw if s.border_set == key_]
            if len(members) != std.BORDERS_PER_SET:
                err(
                    "Switches",
                    f"Standard: the {label.lower()} border set needs {std.BORDERS_PER_SET} switches, "
                    f"found {len(members)}{': ' + ', '.join(members) if members else ''}.",
                )
        for s in sw:
            if s.border_set and s.role != "border":
                err("Switches", f"Standard: {s.name} is in the {s.border_set} border set, so its role must be border.")
            elif s.role == "border" and not s.border_set:
                err("Switches", f"Standard: border {s.name} must be in a border set (client, internal or external).")
            elif "border" in s.role and s.role != "border" and s.role not in SPINE_ROLES:
                err("Switches", f"Standard: role {s.role} on {s.name} isn't part of the design; use border.")

    # --- underlay -------------------------------------------------------------
    u = p.underlay
    g = u.general
    multicast = g.replication_mode == "multicast"
    if g.underlay_routing_loopback_id == g.underlay_vtep_loopback_id:
        err("Underlay", "Routing and VTEP loopback IDs must differ.")
    if multicast:
        rp_ids = {u.multicast.underlay_rp_loopback_id}
        if u.multicast.rp_mode == "bidir":  # phantom-RP loopbacks only exist in bidir mode
            rp_ids.add(u.multicast.underlay_primary_rp_loopback_id)
        if rp_ids & {g.underlay_routing_loopback_id, g.underlay_vtep_loopback_id}:
            err("Underlay", "RP loopback IDs must differ from the routing and VTEP loopback IDs.")
        if spines and u.multicast.rendezvous_points > len(spines):
            err("Underlay", f"{u.multicast.rendezvous_points} rendezvous points requested but only {len(spines)} spine(s).")
    ranges = {
        "routing loopback": u.ipv4.underlay_routing_loopback_ip_range,
        "VTEP loopback": u.ipv4.underlay_vtep_loopback_ip_range,
        "fabric link subnet": u.ipv4.underlay_subnet_ip_range,
    }
    if multicast:
        ranges["RP loopback"] = u.ipv4.underlay_rp_loopback_ip_range
    for (a, na), (b, nb) in combinations(ranges.items(), 2):
        if na.overlaps(nb):
            err("Underlay", f"The {a} range {na} overlaps the {b} range {nb}.")
    for s, ip in zip(sw, mgmt_ips):
        for label, net in ranges.items():
            if ip and ip in net:
                warn("Underlay", f"{s.name} management IP {ip} is inside the {label} range {net}.")

    # --- attach groups --------------------------------------------------------
    groups = p.attach_groups()
    for name, rows in groups.items():
        for d in _dups(a.hostname for a in rows):
            warn("Attach groups", f"Group {name} lists {d} more than once; ports are merged.")
        for a in rows:
            if a.hostname not in by_name:
                err("Attach groups", f"Group {name}: switch {a.hostname} is not in the topology.")
            elif by_name[a.hostname].role not in ATTACHABLE_ROLES:
                warn("Attach groups", f"Group {name}: {a.hostname} is a {by_name[a.hostname].role}, which usually has no attachments.")
    used = {v.vrf_attach_group for v in p.vrfs} | {n.network_attach_group for n in p.networks}
    for name in groups:
        if name not in used:
            warn("Attach groups", f"Group {name} isn't used by any VRF or network.")

    # --- VRFs -----------------------------------------------------------------
    for d in _dups(v.name for v in p.vrfs):
        err("VRFs", f"Duplicate VRF name {d}.")
    for d in _dups(v.vrf_id for v in p.vrfs):
        err("VRFs", f"Duplicate VRF ID (L3 VNI) {d}.")
    for d in _dups(v.vlan_id for v in p.vrfs):
        err("VRFs", f"Duplicate VRF VLAN {d}.")
    for v in p.vrfs:
        if not v.vrf_attach_group:
            warn("VRFs", f"VRF {v.name} has no attach group, so it won't be deployed to any switch.")
        elif v.vrf_attach_group not in groups:
            err("VRFs", f"VRF {v.name} uses attach group {v.vrf_attach_group}, which doesn't exist.")

    # --- networks -------------------------------------------------------------
    vrfs = {v.name: v for v in p.vrfs}
    for d in _dups(n.name for n in p.networks):
        err("Networks", f"Duplicate network name {d}.")
    for d in _dups(n.net_id for n in p.networks):
        err("Networks", f"Duplicate network ID (L2 VNI) {d}.")
    for d in _dups(n.vlan_id for n in p.networks):
        err("Networks", f"Duplicate network VLAN {d}.")
    for vlan in sorted({v.vlan_id for v in p.vrfs} & {n.vlan_id for n in p.networks}):
        err("Networks", f"VLAN {vlan} is used by both a VRF and a network.")
    for vni in sorted({v.vrf_id for v in p.vrfs} & {n.net_id for n in p.networks}):
        err("Networks", f"VNI {vni} is used by both a VRF and a network.")
    for v in [*p.vrfs, *p.networks]:
        if v.vlan_id >= 3968:
            warn("Networks" if hasattr(v, "net_id") else "VRFs", f"{v.name}: VLAN {v.vlan_id} is in the NX-OS reserved range 3968-4094.")
    for n in p.networks:
        if not n.vrf_name:
            err("Networks", f"Network {n.name} has no VRF (Layer-2-only networks aren't supported yet).")
        elif n.vrf_name not in vrfs:
            err("Networks", f"Network {n.name} uses VRF {n.vrf_name}, which doesn't exist.")
        if not n.network_attach_group:
            warn("Networks", f"Network {n.name} has no attach group, so it won't be deployed to any switch.")
        elif n.network_attach_group not in groups:
            err("Networks", f"Network {n.name} uses attach group {n.network_attach_group}, which doesn't exist.")
        elif n.vrf_name in vrfs:
            vrf_hosts = {a.hostname for a in groups.get(vrfs[n.vrf_name].vrf_attach_group or "", [])}
            missing = sorted({a.hostname for a in groups[n.network_attach_group]} - vrf_hosts)
            if missing:
                warn("Networks", f"Network {n.name} is attached to {', '.join(missing)}, where VRF {n.vrf_name} isn't attached.")
    gws = [(n.name, n.gw_ip_address.network) for n in p.networks if n.gw_ip_address]
    for (a, na), (b, nb) in combinations(gws, 2):
        if na.overlaps(nb):
            warn("Networks", f"Gateway subnets of {a} ({na}) and {b} ({nb}) overlap.")

    return issues
