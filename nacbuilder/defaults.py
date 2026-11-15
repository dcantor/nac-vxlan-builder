"""Suggested values so the engineer only edits what differs.

ID starting points follow Nexus Dashboard's default pools: L3 VNI 50000-59000,
L2 VNI 30000-49000, VRF VLANs 2000-2299, network VLANs 2300-2999.
"""

from ipaddress import IPv4Address

from . import standards as std
from .models import Attachment, Management, Network, Project, Switch, Vrf

LEAF_ROLES = {"leaf", "tor"}


def generate_switches(
    prefix: str,
    leafs: int,
    first_mgmt_ip: str | None = None,
    gateway: str | None = None,
    mask: int | None = None,
) -> list[Switch]:
    """A standard fabric: 4 spines, `leafs` leafs, then the client/internal/external border pairs.

    Names: <prefix>-spine1..4, <prefix>-leaf1..N, <prefix>-border-client1..2, -border-internal1..2,
    -border-external1..2. Management IPs are handed out in that order.
    """
    plan: list[tuple[str, str, str | None]] = [(f"spine{i}", "spine", None) for i in range(1, std.SPINE_COUNT + 1)]
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
