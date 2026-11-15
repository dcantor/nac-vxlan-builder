"""Suggested values so the engineer only edits what differs.

ID starting points follow Nexus Dashboard's default pools: L3 VNI 50000-59000,
L2 VNI 30000-49000, VRF VLANs 2000-2299, network VLANs 2300-2999.
"""

from ipaddress import IPv4Address

from .models import ATTACHABLE_ROLES, Attachment, Management, Network, Project, Switch, Vrf


def generate_switches(
    prefix: str,
    spines: int,
    leafs: int,
    borders: int = 0,
    first_mgmt_ip: str | None = None,
    gateway: str | None = None,
    mask: int | None = None,
) -> list[Switch]:
    ip = IPv4Address(first_mgmt_ip) if first_mgmt_ip else None
    out = []
    for role, count in (("spine", spines), ("leaf", leafs), ("border", borders)):
        for i in range(1, count + 1):
            mgmt = None
            if ip or gateway or mask:
                mgmt = Management(management_ipv4_address=ip, default_gateway_v4=gateway or None, subnet_mask_ipv4=mask)
            out.append(Switch(name=f"{prefix}-{role}{i}", role=role, management=mgmt))
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
    return [s for s in p.switches if s.role in ATTACHABLE_ROLES]


def group_all_leafs(p: Project, name: str = "all", ports: list[str] | None = None) -> list[Attachment]:
    return [Attachment(group=name, hostname=s.name, ports=ports or []) for s in _leafs(p)]


def groups_per_leaf(p: Project, ports: list[str] | None = None) -> list[Attachment]:
    return [Attachment(group=s.name, hostname=s.name, ports=ports or []) for s in _leafs(p)]


def merge_attachments(existing: list[Attachment], new: list[Attachment]) -> list[Attachment]:
    seen = {(a.group, a.hostname) for a in existing}
    return existing + [a for a in new if (a.group, a.hostname) not in seen]
