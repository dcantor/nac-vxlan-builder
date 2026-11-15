import re
from typing import Literal, Optional

from pydantic import Field, field_validator

from .base import NacModel
from .fabric import FABRIC_TYPES, Fabric, GlobalIbgp, ManagementServer, SyslogServer
from .interfaces import MODES, Interface, VpcPeer
from .overlay import USED_FOR, Attachment, Network, Vrf
from .preserved import Preserved
from .topology import ATTACHABLE_ROLES, LEAF_ROLE_RE, ROLES, SPINE_ROLES, Management, Switch
from .vrf_lite import VrfLite, VrfLitePeer, VrfLiteSwitch
from .underlay import Underlay, UnderlayGeneral, UnderlayIpv4, UnderlayMulticast, UnderlayOspf


class Project(NacModel):
    """Everything the wizard collects for one fabric. Saved/loaded as JSON."""

    fabric: Fabric = Field(default_factory=lambda: Fabric(name="fabric1"))
    ibgp: GlobalIbgp = Field(
        default_factory=lambda: GlobalIbgp(bgp_asn="65001", route_reflectors=4, overlay_mode="cli")
    )
    switches: list[Switch] = Field(default_factory=list)
    underlay: Underlay = Field(default_factory=Underlay)
    vrfs: list[Vrf] = Field(default_factory=list)
    networks: list[Network] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    vpc_peers: list[VpcPeer] = Field(default_factory=list)
    interfaces: list[Interface] = Field(default_factory=list)
    vrf_lites: list[VrfLite] = Field(default_factory=list)
    preserved: Preserved = Field(default_factory=Preserved)
    # App-only: which house design standard this fabric follows (see standards.py).
    standard: Literal["dc", "dmz", "non_vxlan"] = "dc"
    # App-only, DC Fabric only: a super spine layer of 2 or 4 super spines (they become the route reflectors).
    super_spines: Optional[Literal[2, 4]] = None
    # App-only: hardware model picked per role on the Switches page (used for new switches).
    role_models: dict[str, str] = Field(default_factory=dict)
    # App-only: leaf sub-roles (e.g. compute, storage). Empty = all leafs are alike.
    leaf_roles: list[str] = Field(default_factory=list)

    @field_validator("leaf_roles", mode="before")
    @classmethod
    def _leaf_roles(cls, v):
        if isinstance(v, str):
            v = [x for x in v.replace(",", " ").split() if x]
        out = []
        for x in v or []:
            x = str(x).strip().lower()
            if not re.fullmatch(LEAF_ROLE_RE, x):
                raise ValueError(f"leaf role '{x}' must be lowercase letters, digits, - or _ (max 24)")
            if x not in out:
                out.append(x)
        return out

    def leaf_role_label(self, role: str | None) -> str:
        return f"{role.replace('_', ' ').replace('-', ' ').title()} leafs" if role else "Leafs"

    @property
    def has_super_spines(self) -> bool:
        return self.standard == "dc" and self.super_spines is not None

    @property
    def is_vxlan(self) -> bool:
        return self.standard != "non_vxlan"

    def interfaces_of(self, switch: str) -> list[Interface]:
        return [i for i in self.interfaces if i.switch == switch]

    def model_of(self, switch: str):
        """The switch's hardware model spec (nacbuilder.hardware.SwitchModel) or None."""
        from ..hardware import get

        sw = next((s for s in self.switches if s.name == switch), None)
        return get(sw.model) if sw else None

    def vpc_peer_of(self, switch: str) -> VpcPeer | None:
        return next((v for v in self.vpc_peers if switch in (v.peer1, v.peer2)), None)

    def attach_groups(self, kind: str | None = None) -> dict[str, list[Attachment]]:
        """Rows by group name; with kind="vrf"/"network", only rows written for that kind."""
        groups: dict[str, list[Attachment]] = {}
        for a in self.attachments:
            if kind is None or a.applies_to(kind):
                groups.setdefault(a.group, []).append(a)
        return groups


__all__ = [
    "ATTACHABLE_ROLES",
    "Attachment",
    "FABRIC_TYPES",
    "Fabric",
    "GlobalIbgp",
    "Interface",
    "MODES",
    "Management",
    "ManagementServer",
    "NacModel",
    "Network",
    "Preserved",
    "Project",
    "USED_FOR",
    "ROLES",
    "SPINE_ROLES",
    "Switch",
    "SyslogServer",
    "Underlay",
    "UnderlayGeneral",
    "UnderlayIpv4",
    "UnderlayMulticast",
    "UnderlayOspf",
    "VpcPeer",
    "Vrf",
    "VrfLite",
    "VrfLitePeer",
    "VrfLiteSwitch",
]
