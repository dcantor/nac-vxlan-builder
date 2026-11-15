"""Nexus 9300 hardware catalog (nacbuilder/data/nexus9300.yaml): port layouts and per-model port defaults.

Ports are named Ethernet1/<n>. A breakout port such as Ethernet1/49/1 counts as present when its parent
(Ethernet1/49) is a 40G-or-faster port on the model.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG = Path(__file__).parent / "data" / "nexus9300.yaml"
_PORT = re.compile(r"(?i)^(?:e|eth|ethernet)1/(\d+)(?:/(\d+))?$")
_SPEED = re.compile(r"(\d+)G$")

# Fabric role -> catalog role used to offer models.
ROLE_FAMILY = {
    "spine": "spine", "super_spine": "spine", "border_spine": "spine", "border_gateway_spine": "spine",
    "border_super_spine": "spine", "border_gateway_super_spine": "spine",
    "leaf": "leaf", "tor": "leaf",
    "border": "border", "border_gateway": "border",
    "core_router": None, "edge_router": None,  # any model
}


def _range(text: str | None) -> list[int]:
    if not text:
        return []
    out = []
    for part in str(text).split(","):
        a, _, b = part.strip().partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


@dataclass(frozen=True)
class PortGroup:
    first: int
    last: int
    speed: str
    media: str


@dataclass(frozen=True)
class SwitchModel:
    model: str
    description: str
    roles: tuple[str, ...]
    groups: tuple[PortGroup, ...]
    host: tuple[int, ...]
    uplink: tuple[int, ...]
    spine: tuple[int, ...]

    # --- lookups -----------------------------------------------------------------------
    def numbers(self) -> list[int]:
        return [n for g in self.groups for n in range(g.first, g.last + 1)]

    def group_of(self, n: int) -> PortGroup | None:
        return next((g for g in self.groups if g.first <= n <= g.last), None)

    def has_port(self, name: str) -> bool:
        m = _PORT.match(name.strip().split(".")[0])
        if not m:
            return False
        g = self.group_of(int(m[1]))
        if g is None:
            return False
        return m[2] is None or _gbps(g.speed) >= 40  # breakouts only on 40G+ ports

    def speed(self, name: str) -> str | None:
        m = _PORT.match(name.strip().split(".")[0])
        g = self.group_of(int(m[1])) if m else None
        return g.speed if g else None

    def layout(self) -> str:
        return " · ".join(f"Ethernet1/{g.first}-{g.last} {g.speed} {g.media}" if g.first != g.last
                          else f"Ethernet1/{g.first} {g.speed} {g.media}" for g in self.groups)

    def offered_for(self, role: str) -> bool:
        fam = ROLE_FAMILY.get(role)
        return fam is None or fam in self.roles

    # --- defaults ------------------------------------------------------------------------
    def peer_link(self) -> list[str]:
        """Last two uplink ports (e.g. Ethernet1/53-54 on a 54-port leaf)."""
        return [f"Ethernet1/{n}" for n in self.uplink[-2:]] if len(self.uplink) >= 2 else []

    def spine_uplinks(self, n_spines: int) -> list[str]:
        """Leaf/border ports toward the spines: the first uplink ports, one per spine."""
        return [f"Ethernet1/{n}" for n in self.uplink[:n_spines]]

    def spine_downlink_ports(self) -> list[str]:
        return [f"Ethernet1/{n}" for n in self.spine]

    def super_uplinks(self, n_supers: int) -> list[str]:
        """Spine ports toward the super spines: the last spine-facing ports."""
        return [f"Ethernet1/{n}" for n in self.spine[-n_supers:]] if n_supers else []

    def host_ports(self) -> list[str]:
        return [f"Ethernet1/{n}" for n in self.host]

    def last_host_port(self) -> str | None:
        return f"Ethernet1/{self.host[-1]}" if self.host else None


def _gbps(speed: str) -> int:
    m = _SPEED.search(speed or "")
    return int(m[1]) if m else 0


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[dict, dict]:
    data = yaml.safe_load(Path(path).read_text())
    models = {}
    for m in data.get("models", []):
        groups = tuple(PortGroup(int(g["first"]), int(g["last"]), str(g["speed"]), str(g["media"])) for g in m["ports"])
        models[m["model"]] = SwitchModel(
            model=m["model"], description=m.get("description", ""), roles=tuple(m.get("roles", [])), groups=groups,
            host=tuple(_range(m.get("host_ports"))), uplink=tuple(_range(m.get("uplink_ports"))),
            spine=tuple(_range(m.get("spine_ports"))),
        )
    return models, dict(data.get("suggested", {}))


def catalog(path: Path = CATALOG) -> dict[str, SwitchModel]:
    return _load(str(path))[0]


def suggested(path: Path = CATALOG) -> dict[str, str]:
    return _load(str(path))[1]


def get(model: str | None) -> SwitchModel | None:
    return catalog().get(model) if model else None


def models_for(role: str) -> list[str]:
    return [m for m, spec in catalog().items() if spec.offered_for(role)]
