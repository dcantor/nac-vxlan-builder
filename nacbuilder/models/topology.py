"""`vxlan.topology.switches` (topology_switches.nac.yaml)."""

from ipaddress import IPv4Address
from typing import Literal, Optional

from pydantic import Field

from .base import NacModel

ROLES = (
    "spine",
    "leaf",
    "border",
    "border_spine",
    "border_gateway",
    "border_gateway_spine",
    "super_spine",
    "border_super_spine",
    "border_gateway_super_spine",
    "tor",
    "core_router",
    "edge_router",
)
SPINE_ROLES = {
    "spine",
    "border_spine",
    "border_gateway_spine",
    "super_spine",
    "border_super_spine",
    "border_gateway_super_spine",
}
# Roles that host VRF / network attachments.
ATTACHABLE_ROLES = {"leaf", "border", "border_spine", "border_gateway", "border_gateway_spine", "tor"}

SERIAL_RE = r"^[a-zA-Z0-9_.:-]{1,16}$"


class Management(NacModel):
    default_gateway_v4: Optional[IPv4Address] = None
    management_ipv4_address: Optional[IPv4Address] = None
    subnet_mask_ipv4: Optional[int] = Field(None, ge=8, le=30)


class Switch(NacModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    serial_number: Optional[str] = Field(None, pattern=SERIAL_RE)
    role: Literal[ROLES] = "leaf"
    management: Optional[Management] = None
