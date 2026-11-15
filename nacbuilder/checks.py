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

    S = std.get(p.standard)

    # --- switches -------------------------------------------------------------
    sw = p.switches
    by_name = {s.name: s for s in sw}
    spines = [s for s in sw if s.role in SPINE_ROLES]
    if not sw:
        warn("Switches", "No switches defined yet.")
    elif S.vxlan:
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
    if S.vxlan:
        if p.fabric.type != S.fabric_type:
            err("Fabric", f"Standard: the overlay must be BGP EVPN ({S.fabric_type} with iBGP).")
        if not p.has_super_spines and p.ibgp.route_reflectors != S.route_reflectors:
            err("Fabric", f"Standard: {S.route_reflectors} route reflectors required, found {p.ibgp.route_reflectors}.")
        if p.underlay.general.routing_protocol != S.underlay_protocol:
            err("Underlay", f"Standard: the underlay must be OSPF, found {p.underlay.general.routing_protocol}.")
        supers = [s for s in sw if s.role == "super_spine"]
        plain = [s for s in spines if s.role != "super_spine"]
        if p.has_super_spines and p.ibgp.route_reflectors != p.super_spines:
            err("Fabric", f"Standard: with a super spine layer the {p.super_spines} super spines are the route "
                          f"reflectors (route_reflectors: {p.super_spines}), found {p.ibgp.route_reflectors}.")
        if sw:
            rr_note = "" if p.has_super_spines else " (all route reflectors)"
            if len(plain) != S.spine_count:
                err(
                    "Switches",
                    f"Standard: exactly {S.spine_count} spines{rr_note} required, found {len(plain)}.",
                )
            for s in plain:
                if s.role != "spine":
                    err("Switches", f"Standard: {s.name} must have role spine, not {s.role}.")
            if p.has_super_spines:
                if len(supers) != p.super_spines:
                    err("Switches", f"Standard: the super spine layer needs {p.super_spines} super spines "
                                    f"(route reflectors), found {len(supers)}.")
            elif supers:
                where = ("turn on the super spine layer on the Fabric page" if p.standard == "dc"
                         else f"a {S.label} has no super spine layer")
                err("Switches", f"Standard: {', '.join(s.name for s in supers)} {'is a' if len(supers) == 1 else 'are'} "
                                f"super spine{'s' if len(supers) > 1 else ''}; {where}.")
            for key_, label in S.border_sets.items():
                members = [s.name for s in sw if s.border_set == key_]
                if len(members) != S.borders_per_set:
                    err(
                        "Switches",
                        f"Standard: the {label.lower()} border set needs {S.borders_per_set} switches, "
                        f"found {len(members)}{': ' + ', '.join(members) if members else ''}.",
                    )
            for s in sw:
                if s.border_set and s.role != "border":
                    err("Switches", f"Standard: {s.name} is in the {s.border_set} border set, so its role must be border.")
                elif s.role == "border" and not s.border_set:
                    err("Switches", f"Standard: border {s.name} must be in a border set (client, internal or external).")
                elif "border" in s.role and s.role != "border" and s.role not in SPINE_ROLES:
                    err("Switches", f"Standard: role {s.role} on {s.name} isn't part of the design; use border.")

    else:  # Non-VXLAN design (NaC External fabric)
        for s in sw:
            if S.roles and s.role not in S.roles:
                err("Switches", f"Standard: {s.name} is a {s.role}; a {S.label} uses {' or '.join(S.roles)}.")
        for what, items in (("VRF", p.vrfs), ("network", p.networks), ("VRF-lite profile", p.vrf_lites)):
            if items:
                err("Fabric", f"Standard: a {S.label} has no {what}s, so {len(items)} {what}(s) won't be written. "
                              "Remove them (Day-2 tasks → Decommission) or pick a VXLAN standard.")

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
    vrf_groups = p.attach_groups("vrf")
    net_groups = p.attach_groups("network")
    for name, rows in groups.items():
        for a in rows:
            if a.used_for == "vrf" and a.ports:
                warn("Attach groups", f"Group {name}: ports on {a.hostname} are ignored because the row is used for VRFs only.")

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
        elif v.vrf_attach_group not in vrf_groups:
            err("VRFs", f"VRF {v.name} uses attach group {v.vrf_attach_group}, which has no rows used for VRFs.")

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
            if not p.preserved.networks.get(n.name, {}).get("is_l2_only"):
                err("Networks", f"Network {n.name} has no VRF (Layer-2-only networks aren't supported yet).")
        elif n.vrf_name not in vrfs:
            err("Networks", f"Network {n.name} uses VRF {n.vrf_name}, which doesn't exist.")
        if not n.network_attach_group:
            warn("Networks", f"Network {n.name} has no attach group, so it won't be deployed to any switch.")
        elif n.network_attach_group not in groups:
            err("Networks", f"Network {n.name} uses attach group {n.network_attach_group}, which doesn't exist.")
        elif n.network_attach_group not in net_groups:
            err("Networks", f"Network {n.name} uses attach group {n.network_attach_group}, which has no rows used for networks.")
        elif n.vrf_name in vrfs:
            vrf_hosts = {a.hostname for a in vrf_groups.get(vrfs[n.vrf_name].vrf_attach_group or "", [])}
            missing = sorted({a.hostname for a in net_groups[n.network_attach_group]} - vrf_hosts)
            if missing:
                warn("Networks", f"Network {n.name} is attached to {', '.join(missing)}, where VRF {n.vrf_name} isn't attached.")
    gws = [(n.name, n.gw_ip_address.network) for n in p.networks if n.gw_ip_address]
    for (a, na), (b, nb) in combinations(gws, 2):
        if na.overlaps(nb):
            warn("Networks", f"Gateway subnets of {a} ({na}) and {b} ({nb}) overlap.")

    # --- vPC pairs -------------------------------------------------------------
    paired: dict[str, str] = {}
    for v in p.vpc_peers:
        label = f"vPC {v.peer1}/{v.peer2}"
        for peer in (v.peer1, v.peer2):
            if peer not in by_name:
                err("vPC", f"{label}: switch {peer} is not in the topology.")
            elif by_name[peer].role in SPINE_ROLES:
                err("vPC", f"{label}: {peer} is a spine; spines can't be vPC peers.")
            if peer in paired:
                err("vPC", f"{peer} is in two vPC pairs ({paired[peer]} and {label}).")
            paired[peer] = label
        if v.peer1 in by_name and v.peer2 in by_name and by_name[v.peer1].role != by_name[v.peer2].role:
            warn("vPC", f"{label}: peers have different roles ({by_name[v.peer1].role}, {by_name[v.peer2].role}).")
        links1, links2 = v.peer1_peerlink_interfaces, v.peer2_peerlink_interfaces
        if v.fabric_peering and (links1 or links2):
            err("vPC", f"{label}: use either fabric peering or physical peer-link ports, not both.")
        elif not v.fabric_peering and not (links1 and links2):
            err("vPC", f"{label}: set peer-link ports on both switches, or turn on fabric peering.")
        elif len(links1) != len(links2):
            warn("vPC", f"{label}: peer-link has {len(links1)} port(s) on {v.peer1} but {len(links2)} on {v.peer2}.")
    for d in _dups(v.domain_id for v in p.vpc_peers):
        err("vPC", f"Duplicate vPC domain ID {d}.")
    for key_, label in (S.border_sets if S.vxlan else {}).items():
        members = sorted(s.name for s in sw if s.border_set == key_)
        if len(members) == 2 and not any({v.peer1, v.peer2} == set(members) for v in p.vpc_peers):
            warn("vPC", f"The {label.lower()} border pair ({', '.join(members)}) isn't a vPC pair.")

    # --- interfaces ------------------------------------------------------------
    peerlink_ports = {
        (peer, port.lower())
        for v in p.vpc_peers
        for peer, ports in ((v.peer1, v.peer1_peerlink_interfaces), (v.peer2, v.peer2_peerlink_interfaces))
        for port in ports
    }
    vrf_names = {v.name for v in p.vrfs}
    seen_names: dict[tuple[str, str], int] = {}
    member_of: dict[tuple[str, str], str] = {}
    for i in p.interfaces:
        where = f"{i.switch} {i.name}"
        if i.switch not in by_name:
            err("Interfaces", f"{where}: switch {i.switch} isn't in the topology, so this interface won't be written.")
            continue
        k = (i.switch, i.name.lower())
        seen_names[k] = seen_names.get(k, 0) + 1
        if k in peerlink_ports:
            err("Interfaces", f"{where} is a vPC peer-link port.")
        for m in i.members:
            mk = (i.switch, m.lower())
            if mk in member_of:
                err("Interfaces", f"{i.switch} {m} is a member of both {member_of[mk]} and {i.name}.")
            member_of[mk] = i.name
            if mk in peerlink_ports:
                err("Interfaces", f"{where}: member {m} is a vPC peer-link port.")
        if i.vrf and i.vrf not in vrf_names and i.vrf not in ("default", "management"):
            err("Interfaces", f"{where} uses VRF {i.vrf}, which doesn't exist.")
        if i.vpc_id is not None and not p.vpc_peer_of(i.switch):
            err("Interfaces", f"{where} has vPC ID {i.vpc_id}, but {i.switch} isn't in a vPC pair.")
    for (swname, name), n in seen_names.items():
        if n > 1:
            err("Interfaces", f"{swname} {name} is defined {n} times.")
    for (swname, name) in seen_names:
        if (swname, name) in member_of:
            err("Interfaces", f"{swname} {name} is configured on its own but is also a member of {member_of[(swname, name)]}.")
    for v in p.vpc_peers:
        ids = {}
        for peer in (v.peer1, v.peer2):
            for i in p.interfaces_of(peer):
                if i.vpc_id is not None:
                    ids.setdefault(i.vpc_id, {})[peer] = i
        for vid, sides in ids.items():
            if len(sides) == 1:
                only = next(iter(sides))
                err("Interfaces", f"vPC ID {vid} is only on {only}; add the matching port-channel on its peer.")
            else:
                a, b = sides.values()
                if a.mode != b.mode:
                    err("Interfaces", f"vPC ID {vid}: {a.switch} is {a.mode} but {b.switch} is {b.mode}.")
                elif (a.access_vlan, a.trunk_allowed_vlans, a.native_vlan) != (b.access_vlan, b.trunk_allowed_vlans, b.native_vlan):
                    warn("Interfaces", f"vPC ID {vid}: VLAN settings differ between {a.switch} and {b.switch}.")
    for i in p.interfaces:
        if i.mode == "routed_sub":
            parent = i.name.split(".")[0].lower()
            if not any(j.switch == i.switch and j.name.lower() == parent and j.mode in ("routed", "routed_po") for j in p.interfaces):
                warn("Interfaces", f"{i.switch} {i.name}: parent {i.name.split('.')[0]} isn't defined as a routed interface.")

    # --- VRF-lite ----------------------------------------------------------------
    ifs = {(i.switch, i.name.lower()): i for i in p.interfaces}
    for d in _dups(v.name for v in p.vrf_lites):
        err("VRF-lite", f"Duplicate VRF-lite name {d}.")
    for lite in p.vrf_lites:
        label = f"VRF-lite {lite.name}"
        if lite.vrf not in vrf_names:
            err("VRF-lite", f"{label} extends VRF {lite.vrf}, which doesn't exist.")
        vrf_obj = next((v for v in p.vrfs if v.name == lite.vrf), None)
        vrf_hosts = {a.hostname for a in vrf_groups.get(vrf_obj.vrf_attach_group or "", [])} if vrf_obj else set()
        for s in lite.switches:
            if s.name not in by_name:
                err("VRF-lite", f"{label}: switch {s.name} isn't in the topology.")
                continue
            if by_name[s.name].role not in ("border", "border_spine", "border_gateway", "border_gateway_spine"):
                warn("VRF-lite", f"{label}: {s.name} is a {by_name[s.name].role}; VRF-lite normally runs on borders.")
            if vrf_obj and s.name not in vrf_hosts:
                err("VRF-lite", f"{label}: VRF {lite.vrf} isn't attached to {s.name} (add it to the VRF's attach group).")
            if not s.interfaces:
                err("VRF-lite", f"{label}: {s.name} has no interfaces.")
            if not s.bgp_peers:
                warn("VRF-lite", f"{label}: {s.name} has no eBGP neighbors.")
            nets = []
            for name in s.interfaces:
                i = ifs.get((s.name, name.lower()))
                if i is None:
                    err("VRF-lite", f"{label}: {s.name} {name} isn't defined on the Interfaces page.")
                elif i.vrf != lite.vrf:
                    err("VRF-lite", f"{label}: {s.name} {name} is in VRF {i.vrf or '(none)'}, not {lite.vrf}.")
                elif i.ipv4_address:
                    nets.append(i.ipv4_address.network)
            for peer in s.bgp_peers:
                if nets and not any(peer.address in n for n in nets):
                    warn("VRF-lite", f"{label}: neighbor {peer.address} on {s.name} isn't in any of its VRF-lite interface subnets.")
                if str(peer.remote_as) == p.ibgp.bgp_asn:
                    err("VRF-lite", f"{label}: neighbor {peer.address} uses the fabric's own ASN; VRF-lite here is eBGP.")

    if not S.vxlan:
        skip = {"Underlay", "Attach groups", "VRFs", "Networks", "VRF-lite"}
        issues[:] = [i for i in issues if i.section not in skip]

    # --- settings kept from an imported fabric --------------------------------
    pv = p.preserved
    for section, label, kept, names in (
        ("Switches", "Switch", pv.switches, {s.name for s in p.switches}),
        ("VRFs", "VRF", pv.vrfs, {v.name for v in p.vrfs}),
        ("Networks", "Network", pv.networks, {n.name for n in p.networks}),
    ):
        for name in sorted(set(kept) - names):
            keys = ", ".join(sorted(kept[name]))
            warn(section, f"{label} {name} was removed or renamed, so its imported settings ({keys}) won't be written.")

    return issues
