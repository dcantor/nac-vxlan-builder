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
# Defaults a developer can lock: engineers then see them grayed out and can't change them.
# (The VNI/VLAN pool starts only number new VRFs and networks, so they aren't lockable.)
LOCKABLE = {
    "bgp_asn": "BGP ASN",
    "anycast_gateway_mac": "Anycast gateway MAC",
    "overlay_mode": "Overlay mode",
    "replication_mode": "BUM replication",
    "subnet_mask": "Fabric link mask",
    "routing_loopback_range": "Routing loopback range",
    "vtep_loopback_range": "VTEP loopback range",
    "rp_loopback_range": "RP loopback range",
    "fabric_link_range": "Fabric link subnet range",
    "leaf_roles": "Leaf roles",
    "role_models": "Hardware models",
}


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
    locked: tuple[str, ...] = ()  # LOCKABLE defaults engineers can't change

    def is_locked(self, name: str) -> bool:
        return name in self.locked


_DC_BORDERS = {"client": "Client", "internal": "Internal", "external": "External"}
_VXLAN_RULES = dict(fabric_type="VXLAN_EVPN", vxlan=True, underlay_protocol="ospf", spine_count=4, route_reflectors=4,
                    border_sets=_DC_BORDERS, borders_per_set=2,
                    locked=("anycast_gateway_mac", "overlay_mode", "replication_mode", "subnet_mask"))

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
    d["locked"] = list(s.locked)
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
    data["locked"] = tuple(k for k in LOCKABLE if k in (data.get("locked") or ()))
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


def _role_key(sw) -> str:
    return f"{sw.role}:{sw.leaf_role}" if sw.leaf_role else sw.role


def locked_model(s: Standard, role_key: str) -> str | None:
    """The model a locked standard fixes for a role ('leaf:compute' falls back to 'leaf')."""
    if not s.is_locked("role_models"):
        return None
    rm = s.defaults.role_models
    return rm.get(role_key) or rm.get(role_key.split(":")[0])


def _current(p, name: str):
    u = p.underlay
    return {
        "bgp_asn": lambda: p.ibgp.bgp_asn,
        "anycast_gateway_mac": lambda: p.ibgp.anycast_gateway_mac,
        "overlay_mode": lambda: p.ibgp.overlay_mode or "cli",
        "replication_mode": lambda: u.general.replication_mode,
        "subnet_mask": lambda: u.ipv4.subnet_mask,
        "routing_loopback_range": lambda: str(u.ipv4.underlay_routing_loopback_ip_range),
        "vtep_loopback_range": lambda: str(u.ipv4.underlay_vtep_loopback_ip_range),
        "rp_loopback_range": lambda: str(u.ipv4.underlay_rp_loopback_ip_range),
        "fabric_link_range": lambda: str(u.ipv4.underlay_subnet_ip_range),
        "leaf_roles": lambda: tuple(p.leaf_roles),
    }[name]()


VXLAN_ONLY = {"anycast_gateway_mac", "overlay_mode", "replication_mode", "subnet_mask", "routing_loopback_range",
              "vtep_loopback_range", "rp_loopback_range", "fabric_link_range", "leaf_roles"}


def lock_mismatches(p) -> list[tuple[str, str, object, object]]:
    """(field, label, fabric's value, locked value) for each locked default the fabric doesn't follow."""
    s = get(p.standard)
    out = []
    for name in s.locked:
        if name in VXLAN_ONLY and not s.vxlan:
            continue
        want = getattr(s.defaults, name)
        if name == "role_models":
            for role, m in want.items():
                if p.role_models.get(role) not in (None, m):
                    out.append((name, f"Hardware model for {role.replace(':', ' ')}", p.role_models[role], m))
            for sw in p.switches:
                m = locked_model(s, _role_key(sw))
                if m and sw.model and sw.model != m:
                    out.append((name, f"Hardware model of {sw.name}", sw.model, m))
            continue
        have = _current(p, name)
        if have != want:
            out.append((name, LOCKABLE[name], ", ".join(have) if isinstance(have, tuple) else have,
                        ", ".join(want) if isinstance(want, tuple) else want))
    return out


def apply_locks(p, only: set[str] | None = None):
    """A copy of the fabric with the locked defaults of its standard applied (switch models included).
    `only` limits it to those LOCKABLE names."""
    s, d = get(p.standard), get(p.standard).defaults
    q = p.model_copy(deep=True)

    def lk(name):
        return s.is_locked(name) and (only is None or name in only)
    ib = {k: getattr(d, k) for k in ("bgp_asn", "anycast_gateway_mac", "overlay_mode") if lk(k)}
    if ib:
        q.ibgp = q.ibgp.model_copy(update=ib)
    if s.vxlan:
        if lk("replication_mode"):
            q.underlay.general = q.underlay.general.model_copy(update={"replication_mode": d.replication_mode})
        v4 = {}
        for name, fld in (("subnet_mask", "subnet_mask"), ("routing_loopback_range", "underlay_routing_loopback_ip_range"),
                          ("vtep_loopback_range", "underlay_vtep_loopback_ip_range"),
                          ("rp_loopback_range", "underlay_rp_loopback_ip_range"),
                          ("fabric_link_range", "underlay_subnet_ip_range")):
            if lk(name):
                v4[fld] = getattr(d, name)
        if v4:
            q.underlay.ipv4 = type(q.underlay.ipv4).model_validate({**q.underlay.ipv4.model_dump(), **v4})
        if lk("leaf_roles"):
            q.leaf_roles = list(d.leaf_roles)
    if lk("role_models"):
        q.role_models = {**q.role_models, **d.role_models}
        for sw in q.switches:
            if m := locked_model(s, _role_key(sw)):
                sw.model = m
    return type(p).model_validate(q.model_dump())
