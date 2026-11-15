"""Suggested values so the engineer only edits what differs.

ID starting points follow Nexus Dashboard's default pools: L3 VNI 50000-59000,
L2 VNI 30000-49000, VRF VLANs 2000-2299, network VLANs 2300-2999.
"""

import re
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

from . import standards as std
from .models import (
    Attachment,
    Interface,
    Management,
    Network,
    Project,
    Switch,
    VpcPeer,
    Vrf,
    VrfLite,
    VrfLitePeer,
    VrfLiteSwitch,
)

LEAF_ROLES = {"leaf", "tor"}


def generate_switches(
    prefix: str,
    leafs: int,
    first_mgmt_ip: str | None = None,
    gateway: str | None = None,
    mask: int | None = None,
    super_spines: int = 0,
) -> list[Switch]:
    """A standard fabric: optional super spines, 4 spines, `leafs` leafs, then the client/internal/external
    border pairs.

    Names: <prefix>-superspine1..N, <prefix>-spine1..4, <prefix>-leaf1..N, <prefix>-border-client1..2, -border-internal1..2,
    -border-external1..2. Management IPs are handed out in that order.
    """
    plan: list[tuple[str, str, str | None]] = [(f"superspine{i}", "super_spine", None) for i in range(1, super_spines + 1)]
    plan += [(f"spine{i}", "spine", None) for i in range(1, std.SPINE_COUNT + 1)]
    plan += [(f"leaf{i}", "leaf", None) for i in range(1, leafs + 1)]
    for bset in std.BORDER_SETS:
        plan += [(f"border-{bset}{i}", "border", bset) for i in range(1, std.BORDERS_PER_SET + 1)]

    ip = IPv4Address(first_mgmt_ip) if first_mgmt_ip else None
    out = []
    for suffix, role, bset in plan:
        mgmt = None
        if ip or gateway or mask:
            mgmt = Management(management_ipv4_address=ip, default_gateway_v4=gateway or None, subnet_mask_ipv4=mask)
        out.append(Switch(name=f"{prefix}-{suffix}", role=role, border_set=bset, management=mgmt))
        if ip:
            ip += 1
    return out


def _next_free(used: set[int], start: int, end: int) -> int:
    """Next number after the highest one already used inside [start, end]."""
    n = max([start - 1, *(u for u in used if start <= u <= end)]) + 1
    while n in used:
        n += 1
    return n


def _used_vlans(p: Project) -> set[int]:
    return {v.vlan_id for v in p.vrfs} | {n.vlan_id for n in p.networks}


def _used_vnis(p: Project) -> set[int]:
    return {v.vrf_id for v in p.vrfs} | {n.net_id for n in p.networks}


def _default_group(p: Project) -> str | None:
    groups = p.attach_groups()
    return "all" if "all" in groups else next(iter(groups), None)


def next_vrf(p: Project) -> Vrf:
    names = {v.name for v in p.vrfs}
    i = len(p.vrfs) + 1
    while f"VRF{i:02d}" in names:
        i += 1
    return Vrf(
        name=f"VRF{i:02d}",
        vrf_id=_next_free(_used_vnis(p), 50001, 59000),
        vlan_id=_next_free(_used_vlans(p), 2000, 2299),
        vrf_attach_group=_default_group(p),
    )


def next_network(p: Project) -> Network:
    names = {n.name for n in p.networks}
    i = len(p.networks) + 1
    while f"NET{i:02d}" in names:
        i += 1
    name = f"NET{i:02d}"
    vlan = _next_free(_used_vlans(p), 2300, 2999)
    return Network(
        name=name,
        vrf_name=p.vrfs[0].name if p.vrfs else None,
        net_id=_next_free(_used_vnis(p), 30001, 49000),
        vlan_id=vlan,
        vlan_name=f"{name}_vlan{vlan}",
        network_attach_group=_default_group(p),
    )


def _leafs(p: Project) -> list[Switch]:
    return [s for s in p.switches if s.role in LEAF_ROLES]


def group_all_leafs(p: Project, name: str = "all", ports: list[str] | None = None) -> list[Attachment]:
    """Every leaf (borders are not included; use groups_per_border_set for them)."""
    return [Attachment(group=name, hostname=s.name, ports=ports or []) for s in _leafs(p)]


def groups_per_leaf(p: Project, ports: list[str] | None = None) -> list[Attachment]:
    return [Attachment(group=s.name, hostname=s.name, ports=ports or []) for s in _leafs(p)]


def groups_per_border_set(p: Project, ports: list[str] | None = None) -> list[Attachment]:
    """One group per border pair: border-client, border-internal, border-external."""
    return [
        Attachment(group=f"border-{s.border_set}", hostname=s.name, ports=ports or [])
        for bset in std.BORDER_SETS
        for s in p.switches
        if s.border_set == bset
    ]


def merge_attachments(existing: list[Attachment], new: list[Attachment]) -> list[Attachment]:
    seen = {(a.group, a.hostname) for a in existing}
    return existing + [a for a in new if (a.group, a.hostname) not in seen]


# --- vPC ------------------------------------------------------------------------
def _natural(name: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def pair_vpc(p: Project, peerlink_ports: list[str] | None = None, fabric_peering: bool = False) -> list[VpcPeer]:
    """Suggest vPC pairs: each border set, then leafs in name order (leaf1+leaf2, leaf3+leaf4, ...).

    Switches already in a pair are skipped; domain IDs continue after the highest one in use.
    """
    taken = {x for v in p.vpc_peers for x in (v.peer1, v.peer2)}
    pairs: list[tuple[str, str]] = []
    for bset in std.BORDER_SETS:
        members = sorted((s.name for s in p.switches if s.border_set == bset and s.name not in taken), key=_natural)
        if len(members) == 2:
            pairs.append((members[0], members[1]))
    leafs = sorted((s.name for s in p.switches if s.role == "leaf" and s.name not in taken), key=_natural)
    pairs += list(zip(leafs[0::2], leafs[1::2]))
    # Non-VXLAN designs: core and edge routers pair up the same way
    for role in ("core_router", "edge_router"):
        rs = sorted((s.name for s in p.switches if s.role == role and s.name not in taken), key=_natural)
        pairs += list(zip(rs[0::2], rs[1::2]))
    next_id = max([0, *(v.domain_id or 0 for v in p.vpc_peers)]) + 1
    out = []
    for i, (a, b) in enumerate(pairs):
        links = [] if fabric_peering else (peerlink_ports or [])
        out.append(VpcPeer(peer1=a, peer2=b, domain_id=next_id + i, fabric_peering=fabric_peering or None,
                           peer1_peerlink_interfaces=links, peer2_peerlink_interfaces=links))
    return out


def expand_ports(text: str) -> list[str]:
    """'Ethernet1/1-4, Ethernet1/10, e1/2/1-2' -> each port listed out."""
    out = []
    for part in [x for x in re.split(r"[,\s]+", text) if x]:
        m = re.fullmatch(r"(?i)((?:e|eth|ethernet)(?:\d+/)+)(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"'{part}' isn't a port or range like Ethernet1/1-4")
        prefix, a, b = m[1], int(m[2]), int(m[3]) if m[3] else None
        if b is not None and b < a:
            raise ValueError(f"'{part}': range must go low to high")
        out += [f"{prefix}{n}" for n in range(a, (b or a) + 1)]
    return out


def vpc_port_channel(pair: VpcPeer, po: int, vpc_id: int, members1: list[str], members2: list[str], mode: str,
                     access_vlan: int | None = None, trunk_vlans: str | None = None,
                     description: str | None = None) -> list[Interface]:
    """The matching port-channel on both peers of a vPC pair."""
    common = {"name": f"port-channel{po}", "mode": mode, "vpc_id": vpc_id, "description": description or None}
    if mode == "access":
        common["access_vlan"] = access_vlan
    else:
        common["trunk_allowed_vlans"] = trunk_vlans or None
    return [
        Interface(switch=pair.peer1, members=members1, **common),
        Interface(switch=pair.peer2, members=members2, **common),
    ]


# --- VRF-lite ---------------------------------------------------------------------
@dataclass
class VrfLitePlan:
    lite: VrfLite
    interfaces: list[Interface]  # new routed parents + sub-interfaces
    attachments: list[Attachment]  # rows that attach the VRF to the borders
    vrf_group: str | None  # attach group to set on the VRF if it had none
    links: list[dict]  # for display: switch, interface, local, neighbor


def _used_networks(p: Project) -> list[IPv4Network]:
    return [i.ipv4_address.network for i in p.interfaces if i.ipv4_address]


def build_vrf_lite(p: Project, vrf: str, uplinks: dict[str, list[str]], dot1q_id: int, pool: str, prefix: int,
                   remote_as: int, name: str | None = None) -> VrfLitePlan:
    """VRF-lite over sub-interfaces: one point-to-point subnet per uplink, from `pool`.

    uplinks maps border switch -> parent ports (e.g. {"dc1-border-external1": ["Ethernet1/49"]}).
    The switch gets the first address of each subnet and the eBGP neighbor the second.
    """
    if prefix not in (30, 31):
        raise ValueError("link subnets must be /30 or /31")
    vrf_obj = next((v for v in p.vrfs if v.name == vrf), None)
    if vrf_obj is None:
        raise ValueError(f"VRF {vrf} doesn't exist")
    if any(lite.vrf == vrf and lite.name == (name or f"{vrf}-vrf-lite") for lite in p.vrf_lites):
        raise ValueError(f"VRF-lite {name or vrf + '-vrf-lite'} already exists")
    used = _used_networks(p)
    free = (n for n in IPv4Network(pool).subnets(new_prefix=prefix) if not any(n.overlaps(u) for u in used))
    existing = {(i.switch, i.name.lower()) for i in p.interfaces}
    new_ifs, switches, links = [], [], []
    for sw, parents in uplinks.items():
        lite_ifs, peers = [], []
        for parent in parents:
            parent = expand_ports(parent)[0]
            if (sw, parent.lower()) not in existing and not any(i.switch == sw and i.name.lower() == parent.lower() for i in new_ifs):
                new_ifs.append(Interface(switch=sw, name=parent, mode="routed", description="VRF-lite uplink"))
            sub = f"{parent}.{dot1q_id}"
            if (sw, sub.lower()) in existing:
                raise ValueError(f"{sw} {sub} already exists")
            try:
                net = next(free)
            except StopIteration:
                raise ValueError(f"pool {pool} has no free /{prefix} left") from None
            hosts = [net.network_address, net.network_address + 1] if prefix == 31 else list(net.hosts())[:2]
            new_ifs.append(Interface(switch=sw, name=sub, mode="routed_sub", dot1q_id=dot1q_id, vrf=vrf,
                                     ipv4_address=f"{hosts[0]}/{prefix}", description=f"VRF-lite {vrf}"))
            lite_ifs.append(sub)
            peers.append(VrfLitePeer(address=hosts[1], remote_as=remote_as))
            links.append({"switch": sw, "interface": sub, "local": f"{hosts[0]}/{prefix}", "neighbor": str(hosts[1])})
        switches.append(VrfLiteSwitch(name=sw, interfaces=lite_ifs, bgp_peers=peers))

    # Attach the VRF to the borders. If its group is shared with other VRFs or networks, adding the
    # borders there would deploy those too, so the VRF gets its own copy of the group instead.
    group = vrf_obj.vrf_attach_group
    vrf_group = None
    attachments: list[Attachment] = []
    shared = bool(group) and (
        any(v.name != vrf and v.vrf_attach_group == group for v in p.vrfs)
        or any(n.network_attach_group == group for n in p.networks)
    )
    if not group or shared:
        taken = set(p.attach_groups())
        vrf_group = f"{vrf}-vrf"
        n = 2
        while vrf_group in taken:
            vrf_group, n = f"{vrf}-vrf{n}", n + 1
        if shared:
            attachments += [Attachment(group=vrf_group, hostname=a.hostname, used_for="vrf")
                            for a in p.attach_groups("vrf").get(group, [])]
        group = vrf_group
    have = {a.hostname for a in p.attachments if a.group == group and a.applies_to("vrf")} | {a.hostname for a in attachments}
    attachments += [Attachment(group=group, hostname=sw, used_for="vrf") for sw in uplinks if sw not in have]
    lite = VrfLite(name=name or f"{vrf}-vrf-lite", vrf=vrf, switches=switches)
    return VrfLitePlan(lite, new_ifs, attachments, vrf_group, links)


def apply_vrf_lite_plan(p: Project, plan: VrfLitePlan) -> Project:
    """A copy of `p` with the VRF-lite profile, interfaces, attach rows and VRF group from `plan`."""
    q = p.model_copy(deep=True)
    if plan.vrf_group:
        q.vrfs = [v.model_copy(update={"vrf_attach_group": plan.vrf_group}) if v.name == plan.lite.vrf else v for v in q.vrfs]
    q.vrf_lites.append(plan.lite)
    q.interfaces += plan.interfaces
    q.attachments += plan.attachments
    return q


def generate_external_switches(prefix: str, core: int, edge: int, first_mgmt_ip: str | None = None,
                               gateway: str | None = None, mask: int | None = None) -> list[Switch]:
    """Non-VXLAN design (NaC External fabric): <prefix>-core1..N (core_router), <prefix>-edge1..N (edge_router)."""
    ip = IPv4Address(first_mgmt_ip) if first_mgmt_ip else None
    out = []
    for suffix, role, count in (("core", "core_router", core), ("edge", "edge_router", edge)):
        for i in range(1, count + 1):
            mgmt = Management(management_ipv4_address=ip, default_gateway_v4=gateway or None, subnet_mask_ipv4=mask) \
                if (ip or gateway or mask) else None
            out.append(Switch(name=f"{prefix}-{suffix}{i}", role=role, management=mgmt))
            if ip:
                ip += 1
    return out
