"""Cabling and port plan: what plugs into what, per switch port, for the people racking the gear.

Built from the project: vPC peer links, host ports and port-channels (vPC or not), VRF-lite
uplinks. Spine-to-leaf fabric links aren't in the NaC data (Nexus Dashboard discovers them), so
they're added as a *planned* layout from simple rules (`UplinkPlan`) and marked as such.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field

import pandas as pd

from . import standards as std
from .defaults import _natural, expand_ports
from .models import SPINE_ROLES, Project

LINK_COLUMNS = ["type", "a_switch", "a_port", "b_device", "b_port", "detail", "source"]
PORT_COLUMNS = ["switch", "port", "use", "port_channel", "vpc_id", "mode", "vlans", "ip_vrf", "description", "connects_to"]


def canon(port: str) -> str:
    """Ethernet1/1, eth1/1 and e1/1 are the same port."""
    m = re.fullmatch(r"(?i)(?:e|eth|ethernet)(\d+(?:/\d+){1,2})", port.strip())
    return f"ethernet{m[1]}" if m else port.strip().lower()


@dataclass
class UplinkPlan:
    """Planned spine-leaf cabling: leaf/border port k goes to spine k; spines use consecutive ports per leaf."""

    leaf_uplinks: list[str]  # ports on every leaf/border, one per spine in spine order
    spine_first_port: str = "Ethernet1/1"  # spine port for the first leaf; the next leaf uses the next port
    spine_uplinks: list[str] = field(default_factory=list)  # super spine layer: ports on every spine, one per super spine
    super_first_port: str = "Ethernet1/1"  # super spine port for the first spine; the next spine uses the next port


@dataclass
class CablingPlan:
    links: list[dict] = field(default_factory=list)
    ports: list[dict] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    vpc: list[dict] = field(default_factory=list)
    vrf_lite: list[dict] = field(default_factory=list)


def _sort_ports(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (_natural(r["switch"]), _natural(canon(r["port"]))))


def build_cabling(p: Project, uplinks: UplinkPlan | None = None) -> CablingPlan:
    plan = CablingPlan()
    roles = {s.name: s.role for s in p.switches}
    super_roles = {"super_spine", "border_super_spine", "border_gateway_super_spine"}
    supers = sorted((s.name for s in p.switches if s.role in super_roles), key=_natural)
    spines = sorted((s.name for s in p.switches if s.role in SPINE_ROLES and s.role not in super_roles), key=_natural)
    lower = [s.name for s in p.switches if s.role not in SPINE_ROLES]
    sets = {s.name: s.border_set for s in p.switches}
    order = list(std.BORDER_SETS)

    def tier(n):  # leafs first, then borders in standard order (client, internal, external), then the rest
        if "border" not in roles[n]:
            return 0
        return 1 + (order.index(sets[n]) if sets[n] in order else len(order))

    lower = sorted(lower, key=lambda n: (tier(n), _natural(n)))
    used: dict[tuple[str, str], str] = {}

    def claim(switch: str, port: str, what: str) -> None:
        k = (switch, canon(port))
        if k in used and used[k] != what:
            plan.conflicts.append(f"{switch} {port} is used twice: {used[k]} and {what}.")
        used.setdefault(k, what)

    def port_row(switch, port, use, **kw):
        plan.ports.append({"switch": switch, "port": port, "use": use, **{c: kw.get(c) for c in PORT_COLUMNS[3:]}})

    # vPC peer links
    for v in p.vpc_peers:
        links1, links2 = v.peer1_peerlink_interfaces, v.peer2_peerlink_interfaces
        plan.vpc.append({"vpc_domain": v.domain_id, "peer1": v.peer1, "peer2": v.peer2,
                         "peer_link": "fabric peering" if v.fabric_peering else f"{', '.join(links1)} ↔ {', '.join(links2)}"})
        if len(links1) != len(links2):
            plan.conflicts.append(f"vPC {v.peer1}/{v.peer2}: peer-link port counts differ ({len(links1)} vs {len(links2)}).")
        for a, b in zip(links1, links2):
            plan.links.append({"type": "vPC peer link", "a_switch": v.peer1, "a_port": a, "b_device": v.peer2, "b_port": b,
                               "detail": f"vPC domain {v.domain_id or ''}".strip(), "source": "vpc_peers"})
            claim(v.peer1, a, "vPC peer link")
            claim(v.peer2, b, "vPC peer link")
            port_row(v.peer1, a, "vPC peer link", connects_to=f"{v.peer2} {b}")
            port_row(v.peer2, b, "vPC peer link", connects_to=f"{v.peer1} {a}")

    # interfaces
    subs: dict[tuple[str, str], list] = {}
    for i in p.interfaces:
        if i.mode == "routed_sub":
            subs.setdefault((i.switch, canon(i.name.split(".")[0])), []).append(i)
    lite_by_if = {(s.name, n.lower()): lite for lite in p.vrf_lites for s in lite.switches for n in s.interfaces}
    peer_by_if = {}
    for lite in p.vrf_lites:
        for s in lite.switches:
            for n, name in enumerate(s.interfaces):
                if n < len(s.bgp_peers):
                    peer_by_if[(s.name, name.lower())] = s.bgp_peers[n]

    for i in sorted(p.interfaces, key=lambda i: (_natural(i.switch), _natural(canon(i.name)))):
        if i.mode in ("routed_sub", "loopback"):
            continue
        vlans = (str(i.access_vlan) if i.access_vlan else None) if i.mode == "access" else i.trunk_allowed_vlans
        host = i.description or "host"
        if i.is_port_channel:
            pc_use = f"vPC {i.vpc_id} member" if i.vpc_id else "port-channel member"
            for m in i.members:
                claim(i.switch, m, f"{i.name} member")
                port_row(i.switch, m, pc_use, port_channel=i.name, vpc_id=i.vpc_id, mode=i.mode, vlans=vlans,
                         ip_vrf=f"{i.ipv4_address or ''} {i.vrf or ''}".strip() or None, description=i.description,
                         connects_to=host)
                plan.links.append({"type": "vPC host link" if i.vpc_id else "port-channel link", "a_switch": i.switch,
                                   "a_port": m, "b_device": host, "b_port": None,
                                   "detail": f"{i.name}" + (f", vPC {i.vpc_id}" if i.vpc_id else "") + (f", VLANs {vlans}" if vlans else ""),
                                   "source": "interfaces"})
            continue
        children = subs.get((i.switch, canon(i.name)), [])
        lite_lines, far = [], host
        for c in children:
            lite = lite_by_if.get((i.switch, c.name.lower()))
            peer = peer_by_if.get((i.switch, c.name.lower()))
            lite_lines.append(f"{c.name} dot1q {c.dot1q_id} {c.ipv4_address or ''} vrf {c.vrf or '-'}"
                              + (f" → {peer.address} AS {peer.remote_as}" if peer else ""))
            if lite:
                far = "External router" if host in ("host", "VRF-lite uplink") else host
                plan.vrf_lite.append({"vrf_lite": lite.name, "vrf": lite.vrf, "switch": i.switch, "uplink": i.name,
                                      "sub_interface": c.name, "dot1q": c.dot1q_id,
                                      "local_ip": str(c.ipv4_address) if c.ipv4_address else None,
                                      "neighbor_ip": str(peer.address) if peer else None,
                                      "neighbor_as": peer.remote_as if peer else None})
        use = {"access": "access port", "trunk": "trunk port", "routed": "routed port"}.get(i.mode, i.mode)
        if lite_lines:
            use = "VRF-lite uplink" if any(lite_by_if.get((i.switch, c.name.lower())) for c in children) else "routed (sub-interfaces)"
        claim(i.switch, i.name, use)
        port_row(i.switch, i.name, use, mode=i.mode, vlans=vlans,
                 ip_vrf="; ".join(lite_lines) or (f"{i.ipv4_address or ''} {i.vrf or ''}".strip() or None),
                 description=i.description, connects_to=far)
        plan.links.append({"type": "VRF-lite uplink" if use == "VRF-lite uplink" else f"{use}", "a_switch": i.switch,
                           "a_port": i.name, "b_device": far, "b_port": None,
                           "detail": "; ".join(lite_lines) or (f"VLANs {vlans}" if vlans else None), "source": "interfaces"})

    # planned fabric links
    if uplinks and spines and lower:
        ups = uplinks.leaf_uplinks
        if len(ups) < len(spines):
            plan.conflicts.append(f"{len(spines)} spines but only {len(ups)} uplink port(s) per leaf; "
                                  "spines beyond that get no planned link.")
        m = re.fullmatch(r"(?i)((?:e|eth|ethernet)(?:\d+/)+)(\d+)", uplinks.spine_first_port.strip())
        if not m:
            raise ValueError(f"spine first port '{uplinks.spine_first_port}' isn't like Ethernet1/1")
        prefix, first = m[1], int(m[2])
        for li, leaf in enumerate(lower):
            for si, spine in enumerate(spines[: len(ups)]):
                lp, sp = ups[si], f"{prefix}{first + li}"
                plan.links.append({"type": "fabric link (planned)", "a_switch": leaf, "a_port": lp, "b_device": spine,
                                   "b_port": sp, "detail": "spine-leaf link; ND discovers it", "source": "planned"})
                claim(leaf, lp, "fabric uplink")
                claim(spine, sp, "fabric downlink")
                port_row(leaf, lp, "fabric uplink (planned)", connects_to=f"{spine} {sp}")
                port_row(spine, sp, "fabric downlink (planned)", connects_to=f"{leaf} {lp}")

    # planned super spine links (5-stage fabric)
    if uplinks and supers and spines and uplinks.spine_uplinks:
        ups = uplinks.spine_uplinks
        if len(ups) < len(supers):
            plan.conflicts.append(f"{len(supers)} super spines but only {len(ups)} uplink port(s) per spine; "
                                  "super spines beyond that get no planned link.")
        m = re.fullmatch(r"(?i)((?:e|eth|ethernet)(?:\d+/)+)(\d+)", uplinks.super_first_port.strip())
        if not m:
            raise ValueError(f"super spine first port '{uplinks.super_first_port}' isn't like Ethernet1/1")
        prefix, first = m[1], int(m[2])
        for si, spine in enumerate(spines):
            for ki, sup in enumerate(supers[: len(ups)]):
                sp_port, su_port = ups[ki], f"{prefix}{first + si}"
                plan.links.append({"type": "super spine link (planned)", "a_switch": spine, "a_port": sp_port,
                                   "b_device": sup, "b_port": su_port, "detail": "spine to super spine; ND discovers it",
                                   "source": "planned"})
                claim(spine, sp_port, "super spine uplink")
                claim(sup, su_port, "super spine downlink")
                port_row(spine, sp_port, "super spine uplink (planned)", connects_to=f"{sup} {su_port}")
                port_row(sup, su_port, "spine downlink (planned)", connects_to=f"{spine} {sp_port}")

    plan.ports = _sort_ports(plan.ports)
    return plan


def _port_run(first: str, n: int) -> list[str]:
    m = re.fullmatch(r"(?i)((?:e|eth|ethernet)(?:\d+/)+)(\d+)", first.strip())
    if not m:
        raise ValueError(f"'{first}' isn't like Ethernet1/49")
    return expand_ports(f"{m[1]}{m[2]}-{int(m[2]) + n - 1}") if n > 1 else [first]


def uplink_plan_for(p: Project, first_leaf_uplink: str = "Ethernet1/49", spine_first_port: str = "Ethernet1/1",
                    first_spine_uplink: str = "Ethernet1/61", super_first_port: str = "Ethernet1/1") -> UplinkPlan:
    """Default: one uplink per spine starting at `first_leaf_uplink` (e.g. 4 spines -> Ethernet1/49-52) and, with
    super spines, one uplink per super spine on every spine starting at `first_spine_uplink`."""
    super_roles = {"super_spine", "border_super_spine", "border_gateway_super_spine"}
    n = sum(s.role in SPINE_ROLES and s.role not in super_roles for s in p.switches) or 1
    k = sum(s.role in super_roles for s in p.switches)
    return UplinkPlan(_port_run(first_leaf_uplink, n), spine_first_port,
                      _port_run(first_spine_uplink, k) if k else [], super_first_port)


# --- export ---------------------------------------------------------------------------
def _frames(plan: CablingPlan) -> dict[str, pd.DataFrame]:
    return {
        "Cabling": pd.DataFrame(plan.links, columns=LINK_COLUMNS),
        "Ports": pd.DataFrame(plan.ports, columns=PORT_COLUMNS),
        "vPC pairs": pd.DataFrame(plan.vpc, columns=["vpc_domain", "peer1", "peer2", "peer_link"]),
        "VRF-lite": pd.DataFrame(plan.vrf_lite, columns=["vrf_lite", "vrf", "switch", "uplink", "sub_interface", "dot1q",
                                                        "local_ip", "neighbor_ip", "neighbor_as"]),
    }


def to_xlsx(plan: CablingPlan, fabric: str) -> bytes:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in _frames(plan).items():
            df.to_excel(xw, sheet_name=name, index=False)
        notes = [f"Cabling plan for fabric {fabric}",
                 "Rows with source 'planned' are a suggested spine-leaf layout; Nexus Dashboard discovers fabric links "
                 "and they are not in the NaC YAML.", ""] + (["Conflicts:"] + plan.conflicts if plan.conflicts else ["No conflicts found."])
        pd.DataFrame({"notes": notes}).to_excel(xw, sheet_name="Notes", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="E5E7EB")
            for col in ws.columns:
                width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 2, 10), 70)
            if ws.max_row > 1 and ws.title != "Notes":
                ws.auto_filter.ref = ws.dimensions
    return buf.getvalue()


def to_csv_zip(plan: CablingPlan, fabric: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in _frames(plan).items():
            z.writestr(f"{fabric}-{name.lower().replace(' ', '-')}.csv", df.to_csv(index=False))
    return buf.getvalue()
