"""House design standards. Each fabric follows one, chosen on the Fabric page.

Built-in standards (BUILTIN below):

- **DC Fabric** and **DMZ Fabric** (same rules): iBGP VXLAN_EVPN with a BGP EVPN overlay over an
  OSPF underlay, exactly 4 spines that are all route reflectors, and three border pairs
  (client, internal, external). DC Fabrics may add a super spine layer of 2 or 4 super spines,
  which then are the route reflectors.
- **Non-VXLAN design**: a NaC *External* fabric (`vxlan.global.external`): core and edge routers
  with a BGP ASN, interfaces and vPC pairs; no underlay, VRFs, networks or VRF-lite.

Developers can change the constraints and defaults on the Design standards page. Changes are saved
to nacbuilder/data/standards.yaml (commit it to share them); without that file the built-ins apply.
The chosen standard and each border's set are app-only metadata, not written to the YAML.
"""

import copy
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

STANDARDS_FILE = Path(__file__).parent / "data" / "standards.yaml"
KEYS = ("dc", "dmz", "non_vxlan")
DEFAULT = "dc"
FABRIC_TYPES = ("VXLAN_EVPN", "External")
UNDERLAY_PROTOCOLS = ("ospf", "is-is")


@dataclass(frozen=True)
class Defaults:
    """Values a new fabric starts with, and the pools new VRFs/networks are numbered from."""

    bgp_asn: str = "65001"
    anycast_gateway_mac: str = "20:20:00:00:00:aa"
    overlay_mode: str = "cli"
    replication_mode: str = "multicast"
    subnet_mask: int = 30
    routing_loopback_range: str = "10.2.0.0/22"
    vtep_loopback_range: str = "10.3.0.0/22"
    rp_loopback_range: str = "10.254.254.0/24"
    fabric_link_range: str = "10.4.0.0/16"
    l3_vni_start: int = 50001
    l2_vni_start: int = 30001
    vrf_vlan_start: int = 2000
    network_vlan_start: int = 2300
    leaf_roles: tuple[str, ...] = ()
    role_models: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Standard:
    key: str
    label: str
    summary: str
    fabric_type: str
    vxlan: bool
    underlay_protocol: str | None = None  # None = not enforced
    spine_count: int | None = None  # None = not enforced
    route_reflectors: int | None = None  # None = not enforced
    border_sets: dict = field(default_factory=dict)  # key -> label
    borders_per_set: int = 0
    roles: tuple[str, ...] | None = None  # allowed switch roles (None = any)
    super_spine_counts: tuple[int, ...] = ()  # allowed super spine layer sizes (empty = no super spine option)
    defaults: Defaults = field(default_factory=Defaults)


_DC_BORDERS = {"client": "Client", "internal": "Internal", "external": "External"}
_VXLAN_RULES = dict(fabric_type="VXLAN_EVPN", vxlan=True, underlay_protocol="ospf", spine_count=4, route_reflectors=4,
                    border_sets=_DC_BORDERS, borders_per_set=2)

BUILTIN: dict[str, Standard] = {
    "dc": Standard(
        "dc", "DC Fabric",
        "BGP EVPN overlay · OSPF underlay · 4 spines, all route reflectors · 3 border pairs (client, internal, external)",
        super_spine_counts=(2, 4), **_VXLAN_RULES,
    ),
    "dmz": Standard(
        "dmz", "DMZ Fabric",
        "Same rules as DC Fabric: BGP EVPN overlay · OSPF underlay · 4 spines, all route reflectors · "
        "3 border pairs (client, internal, external)",
        **_VXLAN_RULES,
    ),
    "non_vxlan": Standard(
        "non_vxlan", "Non-VXLAN design",
        "NaC External fabric: core and edge routers with a BGP ASN, interfaces and vPC pairs · "
        "no VXLAN underlay, VRFs, networks or VRF-lite",
        fabric_type="External",
        vxlan=False,
        roles=("core_router", "edge_router"),
        defaults=Defaults(bgp_asn="65100"),
    ),
}

STANDARDS: dict[str, Standard] = {}  # filled by reload(); mutated in place so imports stay current


# --- (de)serialising -----------------------------------------------------------------------------
def to_dict(s: Standard) -> dict:
    d = asdict(s)
    d.pop("key")
    d["defaults"]["leaf_roles"] = list(s.defaults.leaf_roles)
    d["roles"] = list(s.roles) if s.roles is not None else None
    d["super_spine_counts"] = list(s.super_spine_counts)
    return d


def from_dict(key: str, d: dict, base: Standard | None = None) -> Standard:
    """Build a Standard from YAML data, filling anything missing from `base` (the built-in)."""
    base = base or BUILTIN.get(key) or BUILTIN[DEFAULT]
    data = {f.name: getattr(base, f.name) for f in fields(Standard)}
    data.update({k: v for k, v in (d or {}).items() if k in data and k not in ("key", "defaults")})
    dflt = {f.name: getattr(base.defaults, f.name) for f in fields(Defaults)}
    dflt.update({k: v for k, v in ((d or {}).get("defaults") or {}).items() if k in dflt})
    dflt["leaf_roles"] = tuple(dflt.get("leaf_roles") or ())
    dflt["role_models"] = dict(dflt.get("role_models") or {})
    data["key"] = key
    data["vxlan"] = data["fabric_type"] != "External"
    data["roles"] = tuple(data["roles"]) if data.get("roles") else None
    data["super_spine_counts"] = tuple(sorted(int(x) for x in data.get("super_spine_counts") or ()))
    data["border_sets"] = dict(data.get("border_sets") or {})
    data["defaults"] = Defaults(**dflt)
    return Standard(**data)


def load(path: Path | None = None) -> dict[str, Standard]:
    path = Path(path or STANDARDS_FILE)
    if not path.is_file():
        return dict(BUILTIN)
    raw = yaml.safe_load(path.read_text()) or {}
    return {k: from_dict(k, (raw.get("standards") or {}).get(k) or {}) for k in KEYS}


def dump(standards: dict[str, Standard]) -> str:
    header = ("# House design standards for NaC VXLAN Builder, edited on the Design standards page.\n"
              "# Delete this file to go back to the built-in standards.\n")
    return header + yaml.safe_dump({"standards": {k: to_dict(standards[k]) for k in KEYS}}, sort_keys=False)


def save(standards: dict[str, Standard], path: Path | None = None) -> None:
    path = Path(path or STANDARDS_FILE)
    path.write_text(dump(standards))
    reload(path)


def restore_builtin(path: Path | None = None) -> None:
    path = Path(path or STANDARDS_FILE)
    if path.is_file():
        path.unlink()
    reload(path)


def reload(path: Path | None = None) -> None:
    """Re-read the standards file and refresh the module-level values (in place)."""
    STANDARDS.clear()
    STANDARDS.update(load(path))
    dc = STANDARDS["dc"]
    g = globals()
    g["FABRIC_TYPE"] = dc.fabric_type
    g["SPINE_COUNT"] = dc.spine_count or 0
    g["ROUTE_REFLECTORS"] = dc.route_reflectors or 0
    g["UNDERLAY_PROTOCOL"] = dc.underlay_protocol
    g["BORDER_SETS"] = dict(dc.border_sets)
    g["BORDERS_PER_SET"] = dc.borders_per_set
    g["SUPER_SPINE_COUNTS"] = dc.super_spine_counts


# DC values as module constants (kept for older callers; per-fabric code uses get(p.standard)).
FABRIC_TYPE = "VXLAN_EVPN"
SPINE_COUNT = 4
ROUTE_REFLECTORS = 4
UNDERLAY_PROTOCOL = "ospf"
BORDER_SETS = dict(_DC_BORDERS)
BORDERS_PER_SET = 2
SUPER_SPINE_COUNTS = (2, 4)
reload()


def get(key: str | None) -> Standard:
    return STANDARDS.get(key or DEFAULT, STANDARDS[DEFAULT])


def for_fabric_type(fabric_type: str) -> str:
    """Best-guess standard for an imported fabric (DC and DMZ can't be told apart from the YAML)."""
    if fabric_type == "External":
        return next((k for k in KEYS if not get(k).vxlan), "non_vxlan")
    return DEFAULT


def new_project(key: str = DEFAULT):
    """A fresh Project that starts from the standard's defaults."""
    from .models import GlobalIbgp, Project, Underlay, UnderlayGeneral, UnderlayIpv4

    s, d = get(key), get(key).defaults
    p = Project(standard=key)
    p.ibgp = GlobalIbgp(bgp_asn=d.bgp_asn, anycast_gateway_mac=d.anycast_gateway_mac, overlay_mode=d.overlay_mode,
                        route_reflectors=s.route_reflectors if s.route_reflectors in (2, 4) else 4)
    p.fabric = p.fabric.model_copy(update={"type": s.fabric_type})
    p.underlay = Underlay(
        general=UnderlayGeneral(routing_protocol=s.underlay_protocol or "ospf", replication_mode=d.replication_mode),
        ipv4=UnderlayIpv4(subnet_mask=d.subnet_mask, underlay_routing_loopback_ip_range=d.routing_loopback_range,
                          underlay_vtep_loopback_ip_range=d.vtep_loopback_range,
                          underlay_rp_loopback_ip_range=d.rp_loopback_range,
                          underlay_subnet_ip_range=d.fabric_link_range),
    )
    p.leaf_roles = list(d.leaf_roles)
    p.role_models = dict(d.role_models)
    return p


def replace(s: Standard, **changes) -> Standard:
    """A copy of `s` with changes (and `defaults` changes merged)."""
    dflt = changes.pop("defaults", None)
    data = copy.deepcopy(asdict(s))
    data.update(changes)
    if dflt:
        data["defaults"].update(dflt)
    return from_dict(s.key, data, base=s)


def is_customised(path: Path | None = None) -> bool:
    return Path(path or STANDARDS_FILE).is_file()
