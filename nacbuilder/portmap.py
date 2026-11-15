"""Front-panel port map of a switch: which Ethernet ports the YAML configures, and whether they're
enabled (green) or disabled (red, `enabled: false`). Ports the YAML doesn't mention are gray.

A port-channel's member ports take the port-channel's state; breakouts (Ethernet1/49/1) and
sub-interfaces (Ethernet1/1.100) count toward their physical port; vPC peer-link ports are enabled.
"""

import re
from dataclasses import dataclass, field
from html import escape

from .models import Project

_PORT = re.compile(r"(?i)^(?:e|eth(?:ernet)?)1/(\d+)")
ENABLED, DISABLED, UNUSED = "enabled", "disabled", "unused"
COLORS = {ENABLED: "#2e9e44", DISABLED: "#d63b3b", UNUSED: "#c9ccd1"}


@dataclass
class Port:
    number: int
    state: str = UNUSED
    details: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"Ethernet1/{self.number}"


def port_number(name: str) -> int | None:
    m = _PORT.match(name.strip())
    return int(m.group(1)) if m else None


def _vlans(i) -> str:
    if i.mode == "access" and i.access_vlan:
        return f"access VLAN {i.access_vlan}"
    if i.mode == "trunk":
        return f"trunk {i.trunk_allowed_vlans or 'all VLANs'}" + (f", native {i.native_vlan}" if i.native_vlan else "")
    return i.mode


def switch_ports(p: Project, switch: str) -> list[Port]:
    model = p.model_of(switch)  # hardware SwitchModel or None
    ports: dict[int, Port] = {n: Port(n) for n in (model.numbers() if model else [])}

    def mark(n: int | None, enabled: bool, detail: str):
        if n is None:
            return
        port = ports.setdefault(n, Port(n))
        # a disabled entry wins over an enabled one on the same physical port
        port.state = DISABLED if (not enabled or port.state == DISABLED) else ENABLED
        port.details.append(detail)

    for i in p.interfaces_of(switch):
        enabled = i.enabled is not False
        what = f"{i.name}: {_vlans(i)}" + (f", '{i.description}'" if i.description else "") + ("" if enabled else ", disabled")
        if i.members:
            label = f"member of {i.name}" + (f" (vPC {i.vpc_id})" if i.vpc_id else "") + f": {_vlans(i)}"
            label += "" if enabled else ", disabled"
            for m in i.members:
                mark(port_number(m), enabled, label)
        else:
            mark(port_number(i.name), enabled, what)
    for v in p.vpc_peers:
        side = (v.peer1_peerlink_interfaces if v.peer1 == switch else
                v.peer2_peerlink_interfaces if v.peer2 == switch else [])
        for m in side:
            mark(port_number(m), True, f"vPC peer link to {v.peer2 if v.peer1 == switch else v.peer1}")
    if not model and not ports:  # no model and nothing configured: assume a 48+6 leaf
        ports = {n: Port(n) for n in range(1, 55)}
    return [ports[n] for n in sorted(ports)]


def render_svg(p: Project, switches: list[str], highlight: set[tuple[str, int]] = frozenset(),
               selected: tuple[str, int] | None = None, clickable: bool = False) -> tuple[str, int]:
    """SVG of each switch's front panel (odd ports on top, even below, like a Nexus 9300).
    `highlight` outlines (switch, port number) pairs in blue, e.g. the ports a preview adds; `selected`
    outlines one port in orange. `clickable` tags each port with data-switch/data-port for the
    click-to-select component. Returns (svg, height)."""
    pw, ph, gap, left, top = 18, 16, 3, 10, 10
    rows, width, y = [], 0, top
    for sw in switches:
        ports = switch_ports(p, sw)
        m = p.model_of(sw)
        model = m.model if m else None
        cols, x, last_group = [], left, None
        # place ports column by column (pairs), adding a gap between port groups
        for idx in range(0, len(ports), 2):
            pair = ports[idx:idx + 2]
            grp = m.group_of(pair[0].number) if m else None
            if last_group is not None and grp is not last_group:
                x += 10
            last_group = grp
            cols.append((x, pair))
            x += pw + gap
        width = max(width, x + left)
        n_on = sum(pt.state == ENABLED for pt in ports)
        n_off = sum(pt.state == DISABLED for pt in ports)
        title = f"{sw}" + (f" · {model}" if model else " · model not set") + f" · {n_on} enabled · {n_off} disabled"
        rows.append(f'<text x="{left}" y="{y + 12}" font-size="12" font-weight="600" fill="currentColor">{escape(title)}</text>')
        y += 30  # title, then room for the top row's port numbers
        rows.append(f'<rect x="{left - 4}" y="{y - 14}" width="{x - left + 6}" height="{2 * ph + 3 * gap + 34}" rx="4" '
                    f'fill="none" stroke="#8a8f98" stroke-width="1"/>')
        for cx, pair in cols:
            for r, pt in enumerate(pair):
                py = y + r * (ph + gap + 12)
                hl = (sw, pt.number) in highlight
                tip = escape(f"{pt.name} · " + ("not in the YAML" if pt.state == UNUSED else pt.state)
                             + "".join(f"\n{d}" for d in pt.details) + ("\n(new in this preview)" if hl else ""))
                stroke = (' stroke="#f08c00" stroke-width="3"' if selected == (sw, pt.number)
                          else ' stroke="#1f6feb" stroke-width="3"' if hl else ' stroke="#00000033" stroke-width="1"')
                data = f' data-switch="{escape(sw)}" data-port="{pt.number}"' if clickable else ""
                label_y = py - 2 if r == 0 else py + ph + 9  # numbers above the top row, below the bottom row
                rows.append(f'<g><title>{tip}</title><rect x="{cx}" y="{py}" width="{pw}" height="{ph}" rx="2" '
                            f'fill="{COLORS[pt.state]}"{stroke}{data}/></g>')
                rows.append(f'<text x="{cx + pw / 2}" y="{label_y}" font-size="8" text-anchor="middle" '
                            f'fill="currentColor">{pt.number}</text>')
        y += 2 * ph + 3 * gap + 36
    height = y + 4
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="sans-serif">{"".join(rows)}</svg>')
    return svg, height


_COMPONENT = None


def port_picker(svg: str, height: int, key: str):
    """Show a clickable port map; returns {"switch", "port", "click"} for the last click, or None."""
    global _COMPONENT
    import streamlit.components.v1 as components
    from pathlib import Path

    if _COMPONENT is None:
        _COMPONENT = components.declare_component("nacb_portmap", path=str(Path(__file__).parent / "components" / "portmap"))
    return _COMPONENT(svg=svg, height=height, key=key, default=None)
