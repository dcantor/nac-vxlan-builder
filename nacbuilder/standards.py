"""House design standards. Each fabric follows one, chosen on the Fabric page.

- **DC Fabric** and **DMZ Fabric** (same rules): iBGP VXLAN_EVPN with a BGP EVPN overlay over an
  OSPF underlay, exactly 4 spines that are all route reflectors, and three border pairs
  (client, internal, external).
- **DC Fabric with a super spine layer** (optional): 2 or 4 super spines above the 4 spines; the
  super spines are then the route reflectors.
- **Non-VXLAN design**: a NaC *External* fabric (`vxlan.global.external`): core and edge routers
  with a BGP ASN, interfaces and vPC pairs; no underlay, VRFs, networks or VRF-lite.

The chosen standard and each border's set are app-only metadata: they are kept in the project
file, not written to the YAML.
"""

from dataclasses import dataclass, field

# DC/DMZ values, also used directly by helpers that only apply to VXLAN fabrics.
FABRIC_TYPE = "VXLAN_EVPN"
SPINE_COUNT = 4
ROUTE_REFLECTORS = 4
UNDERLAY_PROTOCOL = "ospf"
BORDER_SETS = {"client": "Client", "internal": "Internal", "external": "External"}
BORDERS_PER_SET = 2
SUPER_SPINE_COUNTS = (2, 4)  # allowed sizes of the optional DC super spine layer


@dataclass(frozen=True)
class Standard:
    key: str
    label: str
    summary: str
    fabric_type: str
    vxlan: bool
    underlay_protocol: str | None = None
    spine_count: int | None = None
    route_reflectors: int | None = None
    border_sets: dict = field(default_factory=dict)
    borders_per_set: int = 0
    roles: tuple[str, ...] | None = None  # allowed switch roles (None = any)


_VXLAN_RULES = dict(
    fabric_type=FABRIC_TYPE,
    vxlan=True,
    underlay_protocol=UNDERLAY_PROTOCOL,
    spine_count=SPINE_COUNT,
    route_reflectors=ROUTE_REFLECTORS,
    border_sets=BORDER_SETS,
    borders_per_set=BORDERS_PER_SET,
)

STANDARDS: dict[str, Standard] = {
    "dc": Standard(
        "dc", "DC Fabric",
        "BGP EVPN overlay · OSPF underlay · 4 spines, all route reflectors · 3 border pairs (client, internal, external)",
        **_VXLAN_RULES,
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
    ),
}
DEFAULT = "dc"


def get(key: str | None) -> Standard:
    return STANDARDS.get(key or DEFAULT, STANDARDS[DEFAULT])


def for_fabric_type(fabric_type: str) -> str:
    """Best-guess standard for an imported fabric (DC and DMZ can't be told apart from the YAML)."""
    return "non_vxlan" if fabric_type == "External" else DEFAULT
