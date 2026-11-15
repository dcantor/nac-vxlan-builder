"""Clone a fabric: a copy under a new name, with switch names, serials, management IPs and the
BGP ASN adjusted so it can be deployed next to the original (for example dc1 -> dc2).

Returns a new Project; the original is untouched.
"""

import os
from dataclasses import dataclass
from ipaddress import IPv4Address

from .models import Project
from .models.fabric import validate_asn


@dataclass
class CloneSpec:
    name: str  # new fabric name
    old_prefix: str = ""  # switch-name prefix to replace ("" = keep switch names)
    new_prefix: str = ""
    clear_serials: bool = True  # serial numbers belong to physical switches
    first_mgmt_ip: str | None = None  # new address for the lowest management IP; others shift with it
    bgp_asn: str | None = None  # None = keep


def common_prefix(p: Project) -> str:
    """The switch-name prefix up to and including the last '-' all switches share (e.g. 'dc1-')."""
    names = [s.name for s in p.switches]
    if not names:
        return ""
    pre = os.path.commonprefix(names)
    return pre[: pre.rfind("-") + 1] if "-" in pre else ""


def suggest(p: Project) -> CloneSpec:
    """dc1 -> dc2, fabric9 -> fabric10, else <name>-copy; the switch prefix follows the fabric name."""
    import re

    m = re.fullmatch(r"(.*?)(\d+)", p.fabric.name)
    name = f"{m.group(1)}{int(m.group(2)) + 1}" if m else f"{p.fabric.name}-copy"
    old = common_prefix(p)
    new = old.replace(p.fabric.name, name, 1) if old and p.fabric.name in old else (f"{name}-" if old else "")
    return CloneSpec(name=name, old_prefix=old, new_prefix=new)


def _mgmt_ips(p: Project) -> list[IPv4Address]:
    return [s.management.management_ipv4_address for s in p.switches
            if s.management and s.management.management_ipv4_address]


def clone_fabric(p: Project, spec: CloneSpec) -> Project:
    from .models.fabric import Fabric

    Fabric(name=spec.name)  # validates the name
    if spec.name == p.fabric.name:
        raise ValueError("Give the clone a different fabric name.")
    rename = {}
    if spec.old_prefix and spec.new_prefix != spec.old_prefix:
        rename = {s.name: spec.new_prefix + s.name[len(spec.old_prefix):]
                  for s in p.switches if s.name.startswith(spec.old_prefix)}
        if not rename:
            raise ValueError(f"No switch names start with '{spec.old_prefix}'.")
        clash = {n for n in rename.values()} & ({s.name for s in p.switches} - set(rename))
        if clash or len(set(rename.values())) != len(rename):
            raise ValueError(f"Renaming would give duplicate switch names: {', '.join(sorted(clash)) or 'check the prefix'}.")

    def rn(name: str) -> str:
        return rename.get(name, name)

    delta = 0
    if spec.first_mgmt_ip:
        ips = _mgmt_ips(p)
        if not ips:
            raise ValueError("The fabric has no management IPs to move.")
        delta = int(IPv4Address(spec.first_mgmt_ip)) - int(min(ips))

    def shift(ip):
        if ip is None or not delta:
            return ip
        new = int(ip) + delta
        if not 0 < new < 2**32 - 1:
            raise ValueError(f"Moving {ip} by {delta} leaves the IPv4 range.")
        return IPv4Address(new)

    q = p.model_copy(deep=True)
    q.fabric = q.fabric.model_copy(update={"name": spec.name})
    if spec.bgp_asn:
        q.ibgp = q.ibgp.model_copy(update={"bgp_asn": validate_asn(spec.bgp_asn)})
    for s in q.switches:
        s.name = rn(s.name)
        if spec.clear_serials:
            s.serial_number = None
        if s.management and delta:
            s.management = s.management.model_copy(update={
                "management_ipv4_address": shift(s.management.management_ipv4_address),
                "default_gateway_v4": shift(s.management.default_gateway_v4)})
    for i in q.interfaces:
        i.switch = rn(i.switch)
    for v in q.vpc_peers:
        v.peer1, v.peer2 = rn(v.peer1), rn(v.peer2)
    for a in q.attachments:
        a.hostname = rn(a.hostname)
    for lite in q.vrf_lites:
        for sw in lite.switches:
            sw.name = rn(sw.name)

    pv = q.preserved
    pv.source, pv.files = None, []  # the clone wasn't imported from anywhere
    pv.switches = {rn(k): v for k, v in pv.switches.items()}
    pv.attach = {"/".join([*k.split("/")[:2], rn(k.split("/", 2)[2])]) if k.count("/") >= 2 else k: v
                 for k, v in pv.attach.items()}
    pv.vpc_peers = {"|".join(rn(x) for x in k.split("|")): v for k, v in pv.vpc_peers.items()}
    pv.interfaces = {f"{rn(k.split('/', 1)[0])}/{k.split('/', 1)[1]}" if "/" in k else k: v
                     for k, v in pv.interfaces.items()}
    return Project.model_validate(q.model_dump())
