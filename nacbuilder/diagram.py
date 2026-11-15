"""SVG topology diagram: spines on top, leafs and border pairs below, vPC pairs boxed,
VRF-lite handoffs to an external router cloud. Pure string building, no dependencies."""

import re
from html import escape

from . import standards as std
from .checks import check_project
from .models import SPINE_ROLES, Project

NODE_W, NODE_H = 156, 46
PAIR_GAP, GROUP_GAP, MARGIN = 14, 34, 24
ROW_Y = {"spine": 56, "leaf": 200, "border": 330, "wan": 460}
SUPER_ROW = 144  # extra height when there's a super spine layer
SUPER_ROLES = {"super_spine", "border_super_spine", "border_gateway_super_spine"}

FILL = {
    "super": ("#e0e7ff", "#3730a3"),
    "spine": ("#ede9fe", "#6d28d9"),
    "leaf": ("#dbeafe", "#1d4ed8"),
    "client": ("#ccfbf1", "#0f766e"),
    "internal": ("#fef3c7", "#b45309"),
    "external": ("#fee2e2", "#b91c1c"),
    "border": ("#e5e7eb", "#374151"),
    "other": ("#f3f4f6", "#4b5563"),
}


def _style(s) -> tuple[str, str]:
    if s.role in SUPER_ROLES:
        return FILL["super"]
    if s.role in SPINE_ROLES:
        return FILL["spine"]
    if s.border_set:
        return FILL[s.border_set]
    if s.role == "leaf":
        return FILL["leaf"]
    return FILL["border"] if "border" in s.role else FILL["other"]


def _short(name: str, n: int = 22) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


def render_svg(p: Project) -> str:
    top_roles = SPINE_ROLES if p.is_vxlan else {"core_router"}
    supers = [s for s in p.switches if s.role in SUPER_ROLES] if p.is_vxlan else []
    spines = [s for s in p.switches if s.role in top_roles and s not in supers]
    lower = [s for s in p.switches if s.role not in top_roles]
    # With a super spine layer everything moves down one row.
    Y = {k: v + (SUPER_ROW if supers else 0) for k, v in ROW_Y.items()}
    Y["super"] = ROW_Y["spine"]  # the top row
    messages = [i.message for i in check_project(p) if i.level == "error"]
    errors = {
        s.name for s in p.switches
        if any(re.search(rf"(?<![\w-]){re.escape(s.name)}(?![\w-])", m) for m in messages)
    }

    # Group the lower tier: leafs (vPC pairs together), then each border set, then anything else.
    def order_key(s):
        if s.role == "leaf":
            tier = 0
        elif s.border_set in std.BORDER_SETS:
            tier = 1 + list(std.BORDER_SETS).index(s.border_set)
        else:
            tier = 9
        return tier

    groups: list[list] = []
    placed = set()
    for s in sorted(lower, key=order_key):
        if s.name in placed:
            continue
        pair = p.vpc_peer_of(s.name)
        mate = None
        if pair:
            other = pair.peer2 if pair.peer1 == s.name else pair.peer1
            mate = next((x for x in lower if x.name == other and x.name not in placed), None)
        grp = [s, mate] if mate else [s]
        placed.update(x.name for x in grp)
        groups.append(grp)

    # Leafs (and anything else) on one row, border pairs on the row below.
    rows = {"leaf": [g for g in groups if not any("border" in s.role for s in g)],
            "border": [g for g in groups if any("border" in s.role for s in g)]}

    def row_width(gs):
        return sum(len(g) * NODE_W + (len(g) - 1) * PAIR_GAP for g in gs) + max(0, len(gs) - 1) * GROUP_GAP

    spine_w = len(spines) * NODE_W + max(0, len(spines) - 1) * GROUP_GAP
    super_w = len(supers) * NODE_W + max(0, len(supers) - 1) * GROUP_GAP
    width = max(row_width(rows["leaf"]), row_width(rows["border"]), spine_w, super_w, 440) + 2 * MARGIN
    pos: dict[str, tuple[float, float]] = {}
    group_spans = []
    for row, gs in rows.items():
        x = (width - row_width(gs)) / 2
        for grp in gs:
            start = x
            for i, s in enumerate(grp):
                pos[s.name] = (x, Y[row])
                x += NODE_W + (PAIR_GAP if i < len(grp) - 1 else 0)
            group_spans.append((grp, start, x, Y[row]))
            x += GROUP_GAP
    sx = (width - spine_w) / 2
    for i, s in enumerate(spines):
        pos[s.name] = (sx + i * (NODE_W + GROUP_GAP), Y["spine"])
    ssx = (width - super_w) / 2
    for i, s in enumerate(supers):
        pos[s.name] = (ssx + i * (NODE_W + GROUP_GAP), Y["super"])

    has_wan = bool(p.vrf_lites)
    last = "wan" if has_wan else ("border" if rows["border"] else "leaf")
    height = Y[last] + NODE_H + (40 if has_wan else 34)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height}" width="{width:.0f}" '
        f'height="{height}" style="font-family:system-ui,-apple-system,Segoe UI,sans-serif" role="img" '
        f'aria-label="Topology of fabric {escape(p.fabric.name)}">',
        f'<rect width="{width:.0f}" height="{height}" rx="12" fill="#ffffff"/>',
        f'<text x="{MARGIN}" y="22" font-size="13" font-weight="600" fill="#374151">{escape(p.fabric.name)}'
        f' · {escape(std.get(p.standard).label)} · {"BGP EVPN over OSPF" if p.is_vxlan else "External fabric"}'
        f' · AS {escape(p.ibgp.bgp_asn)}</text>',
    ]

    # fabric links: super spine to every spine, spine to every lower node
    for up in supers:
        x1, y1 = pos[up.name]
        for sp in spines:
            x2, y2 = pos[sp.name]
            out.append(
                f'<line x1="{x1 + NODE_W / 2:.0f}" y1="{y1 + NODE_H}" x2="{x2 + NODE_W / 2:.0f}" y2="{y2}" '
                f'stroke="#6366f1" stroke-opacity="0.45" stroke-width="1.2"/>'
            )
    for sp in spines:
        x1, y1 = pos[sp.name]
        for s in lower:
            x2, y2 = pos[s.name]
            out.append(
                f'<line x1="{x1 + NODE_W / 2:.0f}" y1="{y1 + NODE_H}" x2="{x2 + NODE_W / 2:.0f}" y2="{y2}" '
                f'stroke="#9ca3af" stroke-opacity="0.45" stroke-width="1"/>'
            )

    # group frames, vPC links and labels
    for grp, start, end, gy in group_spans:
        bset = grp[0].border_set if all(s.border_set == grp[0].border_set for s in grp) else None
        label = f"{std.BORDER_SETS[bset]} borders" if bset else ""
        pair = p.vpc_peer_of(grp[0].name) if len(grp) == 2 else None
        if pair:
            label = (label + " · " if label else "") + f"vPC {pair.domain_id or ''}".strip()
            if pair.fabric_peering:
                label += " (fabric peering)"
        if len(grp) == 2 or bset:
            out.append(
                f'<rect x="{start - 7:.0f}" y="{gy - 22}" width="{end - start + 14:.0f}" height="{NODE_H + 44}" '
                f'rx="10" fill="none" stroke="#9ca3af" stroke-dasharray="4 3"/>'
            )
        if label:
            out.append(
                f'<text x="{(start + end) / 2:.0f}" y="{gy - 8}" font-size="11" text-anchor="middle" '
                f'fill="#374151" opacity="0.8">{escape(label)}</text>'
            )
        if pair:
            (ax, ay), (bx, _) = pos[grp[0].name], pos[grp[1].name]
            out.append(
                f'<line x1="{ax + NODE_W:.0f}" y1="{ay + NODE_H / 2}" x2="{bx:.0f}" y2="{ay + NODE_H / 2}" '
                f'stroke="#111827" stroke-width="3"/>'
            )

    # VRF-lite: border -> external router cloud
    if has_wan:
        lite_switches = {}
        for lite in p.vrf_lites:
            for s in lite.switches:
                if s.name in pos:
                    lite_switches.setdefault(s.name, []).append((lite.vrf, {b.remote_as for b in s.bgp_peers}))
        xs = [pos[n][0] + NODE_W / 2 for n in lite_switches]
        if xs:
            cx = sum(xs) / len(xs)
            asns = sorted({a for v in lite_switches.values() for _, s in v for a in s})
            vrfs = sorted({vrf for v in lite_switches.values() for vrf, _ in v})
            for n in lite_switches:
                x1 = pos[n][0] + NODE_W / 2
                out.append(
                    f'<line x1="{x1:.0f}" y1="{pos[n][1] + NODE_H}" x2="{cx:.0f}" y2="{Y["wan"]}" '
                    f'stroke="#b91c1c" stroke-width="1.5" stroke-dasharray="5 3"/>'
                )
            wan_w = 220
            out.append(
                f'<rect x="{cx - wan_w / 2:.0f}" y="{Y["wan"]}" width="{wan_w}" height="{NODE_H + 6}" rx="24" '
                f'fill="#fff1f2" stroke="#b91c1c"/>'
                f'<text x="{cx:.0f}" y="{Y["wan"] + 20}" font-size="12" font-weight="600" text-anchor="middle" '
                f'fill="#7f1d1d">External routers · AS {escape(", ".join(map(str, asns)))}</text>'
                f'<text x="{cx:.0f}" y="{Y["wan"] + 38}" font-size="11" text-anchor="middle" fill="#7f1d1d">'
                f'VRF-lite: {escape(_short(", ".join(vrfs), 34))}</text>'
            )

    # nodes last so they sit on top of the links
    rr_tier = supers if p.has_super_spines else spines
    rr_names = {s.name for s in rr_tier[: p.ibgp.route_reflectors]} if p.is_vxlan else set()
    for s in supers + spines + lower:
        x, y = pos[s.name]
        fill, stroke = _style(s)
        bad = s.name in errors
        out.append(
            f'<g><title>{escape(s.name)} ({escape(s.role)}{", " + escape(s.border_set) if s.border_set else ""})'
            f'{" — has check errors" if bad else ""}</title>'
            f'<rect x="{x:.0f}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="7" fill="{fill}" '
            f'stroke="{"#dc2626" if bad else stroke}" stroke-width="{2.5 if bad else 1.2}"/>'
            f'<text x="{x + NODE_W / 2:.0f}" y="{y + 19}" font-size="12" font-weight="600" text-anchor="middle" '
            f'fill="#111827">{escape(_short(s.name))}</text>'
            f'<text x="{x + NODE_W / 2:.0f}" y="{y + 35}" font-size="10.5" text-anchor="middle" fill="{stroke}">'
            f'{escape(s.role)}{" · RR" if s.name in rr_names else ""}</text></g>'
        )
    out.append("</svg>")
    return "".join(out)
