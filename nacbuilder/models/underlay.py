"""`vxlan.underlay` (underlay.nac.yaml). Defaults follow Nexus Dashboard's."""

from ipaddress import IPv4Address, IPv4Network
from typing import Literal

from pydantic import Field, field_validator

from .base import NacModel


class UnderlayGeneral(NacModel):
    routing_protocol: Literal["ospf", "is-is"] = "ospf"
    enable_ipv6_underlay: bool = False
    replication_mode: Literal["multicast", "ingress"] = "multicast"
    underlay_routing_loopback_id: int = Field(0, ge=0, le=1023)
    underlay_vtep_loopback_id: int = Field(1, ge=0, le=1023)
    underlay_routing_protocol_tag: str = Field("UNDERLAY", min_length=1, max_length=20, pattern=r"^\S+$")
    intra_fabric_interface_mtu: int = Field(9216, ge=576, le=9216)
    layer2_host_interface_mtu: int = Field(9216, ge=1500, le=9216)
    unshut_host_interfaces: bool = True


class UnderlayIpv4(NacModel):
    fabric_interface_numbering: Literal["p2p", "unnumbered"] = "p2p"
    subnet_mask: Literal[30, 31] = 30
    underlay_routing_loopback_ip_range: IPv4Network = IPv4Network("10.2.0.0/22")
    underlay_vtep_loopback_ip_range: IPv4Network = IPv4Network("10.3.0.0/22")
    underlay_rp_loopback_ip_range: IPv4Network = IPv4Network("10.254.254.0/24")
    underlay_subnet_ip_range: IPv4Network = IPv4Network("10.4.0.0/16")


class UnderlayOspf(NacModel):
    area_id: str = "0.0.0.0"
    authentication_enable: bool = False
    authentication_key_id: int = Field(0, ge=0, le=255)
    authentication_key: str = ""

    @field_validator("area_id", mode="before")
    @classmethod
    def _area(cls, v):
        v = str(v).strip()
        if v.isdigit():
            if int(v) > 4294967295:
                raise ValueError("OSPF area must be 0-4294967295 or dotted decimal")
            return v
        try:
            IPv4Address(v)
        except ValueError:
            raise ValueError("OSPF area must be a number or dotted decimal like 0.0.0.0") from None
        return v


class UnderlayMulticast(NacModel):
    rendezvous_points: Literal[2, 4] = 2
    rp_mode: Literal["asm", "bidir"] = "asm"
    underlay_rp_loopback_id: int = Field(254, ge=0, le=1023)
    underlay_primary_rp_loopback_id: int = Field(2, ge=0, le=1023)


class Underlay(NacModel):
    general: UnderlayGeneral = Field(default_factory=UnderlayGeneral)
    ipv4: UnderlayIpv4 = Field(default_factory=UnderlayIpv4)
    ospf: UnderlayOspf = Field(default_factory=UnderlayOspf)
    multicast: UnderlayMulticast = Field(default_factory=UnderlayMulticast)

    def to_nac(self) -> dict:
        """Emit only the sections that apply to the chosen protocol/replication mode."""
        d = super().to_nac()
        if self.general.routing_protocol != "ospf":
            d.pop("ospf")
        elif not self.ospf.authentication_enable:
            d["ospf"].pop("authentication_key_id")
            d["ospf"].pop("authentication_key")
        if self.general.replication_mode != "multicast":
            d.pop("multicast")
            d["ipv4"].pop("underlay_rp_loopback_ip_range")
        return d
