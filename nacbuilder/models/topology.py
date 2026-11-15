"""`vxlan.topology.switches` (topology_switches.nac.yaml)."""

from ipaddress import IPv4Address
from typing import Literal, Optional

from pydantic import Field, field_validator

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
LEAF_ROLE_RE = r"^[a-z][a-z0-9_-]{0,23}$"


class Management(NacModel):
    default_gateway_v4: Optional[IPv4Address] = None
    management_ipv4_address: Optional[IPv4Address] = None
    subnet_mask_ipv4: Optional[int] = Field(None, ge=8, le=30)


class Switch(NacModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    serial_number: Optional[str] = Field(None, pattern=SERIAL_RE)
    role: Literal[ROLES] = "leaf"
    management: Optional[Management] = None
    # App-only: which border pair this switch belongs to (see standards.py). Not in the NaC schema.
    border_set: Optional[str] = Field(None, pattern=r"^[a-z][a-z0-9_-]{0,23}$")
    # App-only: hardware model from the Nexus 9300 catalog (drives port numbering and port checks).
    model: Optional[str] = Field(None, max_length=40)
    # App-only: leaf sub-role such as compute or storage (see Project.leaf_roles).
    leaf_role: Optional[str] = Field(None, pattern=LEAF_ROLE_RE)

    @field_validator("leaf_role", mode="before")
    @classmethod
    def _leaf_role(cls, v):
        return v.strip().lower() if isinstance(v, str) and v.strip() else None

    def to_nac(self) -> dict:
        d = super().to_nac()
        for k in ("border_set", "model", "leaf_role"):
            d.pop(k, None)
        return d
