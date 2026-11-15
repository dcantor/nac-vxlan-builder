from pydantic import Field

from .base import NacModel
from .fabric import FABRIC_TYPES, Fabric, GlobalIbgp, ManagementServer, SyslogServer
from .overlay import Attachment, Network, Vrf
from .topology import ATTACHABLE_ROLES, ROLES, SPINE_ROLES, Management, Switch
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

    def attach_groups(self) -> dict[str, list[Attachment]]:
        groups: dict[str, list[Attachment]] = {}
        for a in self.attachments:
            groups.setdefault(a.group, []).append(a)
        return groups


__all__ = [
    "ATTACHABLE_ROLES",
    "Attachment",
    "FABRIC_TYPES",
    "Fabric",
    "GlobalIbgp",
    "Management",
    "ManagementServer",
    "NacModel",
    "Network",
    "Project",
    "ROLES",
    "SPINE_ROLES",
    "Switch",
    "SyslogServer",
    "Underlay",
    "UnderlayGeneral",
    "UnderlayIpv4",
    "UnderlayMulticast",
    "UnderlayOspf",
    "Vrf",
]
