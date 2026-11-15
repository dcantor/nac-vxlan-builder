"""`vxlan.overlay` VRFs, networks and attach groups (vrfs.nac.yaml, networks.nac.yaml)."""

import re
from ipaddress import IPv4Interface, IPv6Interface
from typing import Literal, Optional

from pydantic import Field, field_validator

from .base import NacModel

# Port regex copied from the NaC schema (overlay_network_attach_group_switch.ports).
PORT_RE = re.compile(
    r"(?i)^(?:e|eth(?:ernet)?)((\d)/\d{1,3})$"
    r"|^(?:po|port-channel)([1-9]|[1-9][0-9]{1,2}|[1-3][0-9]{3}|40[0-8][0-9]|409[0-6])$"
)
NAME_RE = r"^[A-Za-z0-9_.:-]+$"


class Vrf(NacModel):
    name: str = Field(min_length=1, max_length=32, pattern=NAME_RE)
    vrf_id: int = Field(ge=1, le=16777214, description="L3 VNI")
    vlan_id: int = Field(ge=2, le=4094)
    vrf_attach_group: Optional[str] = None


class Network(NacModel):
    name: str = Field(min_length=1, max_length=64, pattern=NAME_RE)
    vrf_name: Optional[str] = None
    net_id: int = Field(ge=1, le=16777214, description="L2 VNI")
    vlan_id: int = Field(ge=2, le=4094)
    vlan_name: Optional[str] = Field(None, max_length=128)
    int_desc: Optional[str] = Field(None, max_length=254)
    gw_ip_address: Optional[IPv4Interface] = None
    gw_ipv6_address: Optional[IPv6Interface] = None
    mtu_l3intf: Optional[int] = Field(None, ge=68, le=9216)
    route_target_both: Optional[bool] = None
    l3gw_on_border: Optional[bool] = None
    network_attach_group: Optional[str] = None

    @field_validator("gw_ip_address")
    @classmethod
    def _gw(cls, v):
        if v is not None and v.network.prefixlen < 31 and v.ip in (v.network.network_address, v.network.broadcast_address):
            raise ValueError("gateway must be a host address, e.g. 192.168.10.1/24")
        return v


USED_FOR = ("both", "vrf", "network")


class Attachment(NacModel):
    """One row of an attach group: a switch (and, for networks, its access ports).

    `used_for` says which list the row is written to: `vrf_attach_groups`,
    `network_attach_groups` or both. A group can then have different members for VRFs
    and networks, as in Cisco's example where VRF group `all` has four leafs but
    network group `all` has only two.
    """

    group: str = Field(min_length=1, max_length=64, pattern=NAME_RE)
    hostname: str = Field(min_length=1)
    ports: list[str] = Field(default_factory=list)
    used_for: Literal[USED_FOR] = "both"

    def applies_to(self, kind: str) -> bool:
        return self.used_for in ("both", kind)

    @field_validator("ports", mode="before")
    @classmethod
    def _ports(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [p for p in re.split(r"[,\s]+", v) if p]
        bad = [p for p in v if not PORT_RE.match(p)]
        if bad:
            raise ValueError(f"invalid port(s) {', '.join(bad)}; use Ethernet1/13 or port-channel10")
        return v
