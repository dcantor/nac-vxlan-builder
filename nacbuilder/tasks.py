"""Day-2 tasks that touch several sections at once.

Every task takes the current Project and returns a *new* one; nothing is changed in place, so
the UI can preview the result (compare_projects + check_project) before applying it.
"""

import re
from dataclasses import dataclass

from .defaults import (
    _natural,
    apply_vrf_lite_plan,
    build_vrf_lite,
    expand_ports,
    group_all_leafs,
    next_network,
    next_vrf,
)
from .models import Attachment, Interface, Management, Network, Project, Switch, VpcPeer, Vrf


@dataclass
class NetworkSpec:
    name: str
    gw_ip_address: str | None = None
    vlan_id: int | None = None
    net_id: int | None = None


@dataclass
class VrfLiteSpec:
    switches: list[str]
    uplinks: list[str]
    pool: str
    prefix: int
    remote_as: int
    dot1q_id: int | None = None  # default: the VRF's VLAN


@dataclass
class HostPorts:
    ports: str  # e.g. "Ethernet1/1-10": one vPC port-channel per port, same port on both peers
    mode: str = "trunk"
    access_vlan: int | None = None
    trunk_vlans: str | None = None
    description: str | None = None


def _copy(p: Project) -> Project:
    return p.model_copy(deep=True)


# --- new tenant -------------------------------------------------------------------
def new_tenant(
    p: Project,
    vrf_name: str,
    networks: list[NetworkSpec],
    attach_group: str = "all",
    vrf_id: int | None = None,
    vrf_vlan: int | None = None,
    vrf_lite: VrfLiteSpec | None = None,
) -> Project:
    """A VRF, its networks, the attach group they use (created with every leaf if missing) and,
    optionally, a VRF-lite handoff on the borders."""
    q = _copy(p)
    if any(v.name == vrf_name for v in q.vrfs):
        raise ValueError(f"VRF {vrf_name} already exists")
    if attach_group and attach_group not in q.attach_groups():
        rows = group_all_leafs(q, name=attach_group)
        if not rows:
            raise ValueError("there are no leafs to put in a new attach group")
        q.attachments += rows
    suggested = next_vrf(q)
    q.vrfs.append(Vrf(
        name=vrf_name,
        vrf_id=vrf_id or suggested.vrf_id,
        vlan_id=vrf_vlan or suggested.vlan_id,
        vrf_attach_group=attach_group or None,
    ))
    names = [n.name for n in networks]
    dup = {n for n in names if names.count(n) > 1} | {n for n in names if any(x.name == n for x in q.networks)}
    if dup:
        raise ValueError(f"network name(s) already used: {', '.join(sorted(dup))}")
    for spec in networks:
        nxt = next_network(q)
        vlan = spec.vlan_id or nxt.vlan_id
        q.networks.append(Network(
            name=spec.name,
            vrf_name=vrf_name,
            net_id=spec.net_id or nxt.net_id,
            vlan_id=vlan,
            vlan_name=f"{spec.name}_vlan{vlan}",
            gw_ip_address=spec.gw_ip_address or None,
            network_attach_group=attach_group or None,
        ))
    if vrf_lite:
        vrf = q.vrfs[-1]
        plan = build_vrf_lite(q, vrf_name, {s: vrf_lite.uplinks for s in vrf_lite.switches},
                              vrf_lite.dot1q_id or vrf.vlan_id, vrf_lite.pool, vrf_lite.prefix, vrf_lite.remote_as)
        q = apply_vrf_lite_plan(q, plan)
    return q


# --- onboard a leaf pair -------------------------------------------------------------
def next_leaf_names(p: Project, prefix: str | None = None) -> tuple[str, str]:
    """The next two free leaf names, following the existing `<prefix>-leafN` pattern."""
    leafs = [s.name for s in p.switches if s.role == "leaf"]
    if prefix is None:
        m = next((re.match(r"(.*?)leaf\d+$", n) for n in sorted(leafs, key=_natural)), None)
        prefix = m[1] if m else f"{p.fabric.name}-"
    used = {int(m[1]) for n in leafs if (m := re.fullmatch(rf"{re.escape(prefix)}leaf(\d+)", n))}
    n = max(used, default=0) + 1
    while n in used or n + 1 in used:
        n += 1
    return f"{prefix}leaf{n}", f"{prefix}leaf{n + 1}"


def next_mgmt_ips(p: Project, count: int = 2) -> tuple[list[str], int | None, str | None]:
    """Next free management IPs after the highest one in use, plus the common mask and gateway."""
    mgmts = [s.management for s in p.switches if s.management and s.management.management_ipv4_address]
    if not mgmts:
        return [], None, None
    used = {m.management_ipv4_address for m in mgmts}
    gws = {m.default_gateway_v4 for m in mgmts if m.default_gateway_v4}
    masks = {m.subnet_mask_ipv4 for m in mgmts if m.subnet_mask_ipv4}
    ip = max(used) + 1
    out = []
    while len(out) < count:
        if ip not in used and ip not in gws:
            out.append(str(ip))
        ip += 1
    return out, (masks.pop() if len(masks) == 1 else None), (str(gws.pop()) if len(gws) == 1 else None)


def onboard_leaf_pair(
    p: Project,
    names: tuple[str, str],
    serials: tuple[str | None, str | None] = (None, None),
    mgmt_ips: tuple[str | None, str | None] = (None, None),
    mask: int | None = None,
    gateway: str | None = None,
    peerlink_ports: list[str] | None = None,
    fabric_peering: bool = False,
    host_ports: HostPorts | None = None,
    groups: list[str] | None = None,
) -> Project:
    """Two leafs as a vPC pair, with optional host vPC port-channels and attach group membership."""
    q = _copy(p)
    a, b = names
    if a == b:
        raise ValueError("the two leafs need different names")
    clash = [n for n in names if any(s.name == n for s in q.switches)]
    if clash:
        raise ValueError(f"switch(es) already exist: {', '.join(clash)}")
    for name, serial, ip in zip(names, serials, mgmt_ips):
        mgmt = Management(management_ipv4_address=ip or None, subnet_mask_ipv4=mask, default_gateway_v4=gateway or None) \
            if (ip or mask or gateway) else None
        q.switches.append(Switch(name=name, role="leaf", serial_number=serial or None, management=mgmt))
    links = [] if fabric_peering else (peerlink_ports or [])
    domain = max([0, *(v.domain_id or 0 for v in q.vpc_peers)]) + 1
    pair = VpcPeer(peer1=a, peer2=b, domain_id=domain, fabric_peering=fabric_peering or None,
                   peer1_peerlink_interfaces=links, peer2_peerlink_interfaces=links)
    q.vpc_peers.append(pair)
    if host_ports and host_ports.ports.strip():
        used_po = {int(m[1]) for i in q.interfaces if (m := re.fullmatch(r"(?i)(?:po|port-channel)(\d+)", i.name))}
        po = max([10, *used_po]) + 1
        for port in expand_ports(host_ports.ports):
            if port.lower() in {x.lower() for x in links}:
                raise ValueError(f"{port} is a peer-link port")
            common = dict(name=f"port-channel{po}", mode=host_ports.mode, vpc_id=po, members=[port],
                          description=host_ports.description or None)
            if host_ports.mode == "access":
                common["access_vlan"] = host_ports.access_vlan
            else:
                common["trunk_allowed_vlans"] = host_ports.trunk_vlans or None
            q.interfaces += [Interface(switch=a, **common), Interface(switch=b, **common)]
            po += 1
    for g in groups or []:
        q.attachments += [Attachment(group=g, hostname=n) for n in names]
    # A VRF can have its own attach group (e.g. after VRF-lite copied a shared group). If its networks
    # now reach the new leafs, the VRF must too, or the networks would sit on leafs without their VRF.
    vrf_groups = {v.name: v.vrf_attach_group for v in q.vrfs}
    have = {(a.group, a.hostname) for a in q.attachments if a.applies_to("vrf")}
    for n in q.networks:
        vg = vrf_groups.get(n.vrf_name)
        if n.network_attach_group in (groups or []) and vg and vg != n.network_attach_group:
            for leaf in names:
                if (vg, leaf) not in have:
                    q.attachments.append(Attachment(group=vg, hostname=leaf, used_for="vrf"))
                    have.add((vg, leaf))
    return q


# --- decommission --------------------------------------------------------------------
def remove_vrf_lite(p: Project, name: str, drop_interfaces: bool = True) -> Project:
    """Delete a VRF-lite profile and (optionally) its sub-interfaces and now-unused routed parents."""
    q = _copy(p)
    lite = next((v for v in q.vrf_lites if v.name == name), None)
    if lite is None:
        return q
    q.vrf_lites = [v for v in q.vrf_lites if v.name != name]
    if drop_interfaces:
        gone = {(s.name, n.lower()) for s in lite.switches for n in s.interfaces}
        q.interfaces = [i for i in q.interfaces if (i.switch, i.name.lower()) not in gone]
        q.interfaces = [
            i for i in q.interfaces
            if not (i.mode == "routed" and i.description == "VRF-lite uplink" and not i.ipv4_address
                    and not any(j.switch == i.switch and j.name.lower().startswith(i.name.lower() + ".") for j in q.interfaces))
        ]
    return q


def decommission(p: Project, switches: list[str] = (), vrfs: list[str] = (), include_vpc_peer: bool = True) -> Project:
    """Remove switches and/or VRFs plus everything that references them.

    Switches: their interfaces, vPC pair (and, by default, the vPC peer), attach-group rows,
    VRF-lite entries and kept imported settings. VRFs: their networks, VRF-lite profiles (with
    sub-interfaces), routed interfaces in the VRF and kept settings.
    """
    q = _copy(p)
    gone_sw = set(switches)
    if include_vpc_peer:
        for v in q.vpc_peers:
            if {v.peer1, v.peer2} & gone_sw:
                gone_sw |= {v.peer1, v.peer2}
    unknown = gone_sw - {s.name for s in q.switches}
    if unknown:
        raise ValueError(f"unknown switch(es): {', '.join(sorted(unknown))}")
    gone_vrf = set(vrfs)
    if gone_vrf - {v.name for v in q.vrfs}:
        raise ValueError(f"unknown VRF(s): {', '.join(sorted(gone_vrf - {v.name for v in q.vrfs}))}")

    groups_before = {v.vrf_attach_group for v in q.vrfs if v.name in gone_vrf} | {
        n.network_attach_group for n in q.networks if n.vrf_name in gone_vrf}

    # VRFs first (their VRF-lite profiles may reference switches being removed too)
    for lite in [v for v in q.vrf_lites if v.vrf in gone_vrf]:
        q = remove_vrf_lite(q, lite.name)
    gone_nets = {n.name for n in q.networks if n.vrf_name in gone_vrf}
    q.vrfs = [v for v in q.vrfs if v.name not in gone_vrf]
    q.networks = [n for n in q.networks if n.name not in gone_nets]
    q.interfaces = [i for i in q.interfaces if i.vrf not in gone_vrf]
    still_used = {v.vrf_attach_group for v in q.vrfs} | {n.network_attach_group for n in q.networks}
    orphaned = {g for g in groups_before if g and g not in still_used}
    q.attachments = [a for a in q.attachments if a.group not in orphaned]  # groups only the removed items used

    # switches
    q.switches = [s for s in q.switches if s.name not in gone_sw]
    q.interfaces = [i for i in q.interfaces if i.switch not in gone_sw]
    q.vpc_peers = [v for v in q.vpc_peers if not ({v.peer1, v.peer2} & gone_sw)]
    q.attachments = [a for a in q.attachments if a.hostname not in gone_sw]
    lites = []
    for lite in q.vrf_lites:
        kept = [s for s in lite.switches if s.name not in gone_sw]
        if kept:
            lites.append(lite.model_copy(update={"switches": kept}))
    q.vrf_lites = lites
    # vPC port-channels left on a peer whose pair is gone lose their vpc_id
    paired = {x for v in q.vpc_peers for x in (v.peer1, v.peer2)}
    q.interfaces = [i.model_copy(update={"vpc_id": None}) if i.vpc_id and i.switch not in paired else i for i in q.interfaces]

    pv = q.preserved
    q.preserved = pv.model_copy(update={
        "switches": {k: v for k, v in pv.switches.items() if k not in gone_sw},
        "interfaces": {k: v for k, v in pv.interfaces.items() if k.split("/", 1)[0] not in gone_sw},
        "vpc_peers": {k: v for k, v in pv.vpc_peers.items() if not (set(k.split("|")) & gone_sw)},
        "vrfs": {k: v for k, v in pv.vrfs.items() if k not in gone_vrf},
        "networks": {k: v for k, v in pv.networks.items() if k not in gone_nets},
    })
    return q


def border_switches(p: Project, bset: str = "external") -> list[str]:
    return sorted((s.name for s in p.switches if s.border_set == bset), key=_natural)


__all__ = [
    "HostPorts",
    "NetworkSpec",
    "VrfLiteSpec",
    "border_switches",
    "decommission",
    "new_tenant",
    "next_leaf_names",
    "next_mgmt_ips",
    "onboard_leaf_pair",
    "remove_vrf_lite",
]
