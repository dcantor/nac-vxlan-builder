"""House design standard every fabric built with this app must follow.

- Overlay: BGP EVPN (iBGP VXLAN_EVPN fabric, `vxlan.global.ibgp`).
- Underlay: OSPF.
- Exactly 4 spines (role `spine`), and all 4 are BGP route reflectors.
- Three border pairs (role `border`): client, internal and external.

The border set is app-only metadata (`Switch.border_set`); the NaC data model has no
field for it, so it is kept in the project file but not written to the YAML.
"""

FABRIC_TYPE = "VXLAN_EVPN"
SPINE_COUNT = 4
ROUTE_REFLECTORS = 4
UNDERLAY_PROTOCOL = "ospf"

BORDER_SETS = {"client": "Client", "internal": "Internal", "external": "External"}
BORDERS_PER_SET = 2
