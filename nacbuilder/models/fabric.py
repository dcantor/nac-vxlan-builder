"""`vxlan.fabric` and `vxlan.global.ibgp` (global.nac.yaml)."""

import re
from ipaddress import IPv4Address, IPv6Address
from typing import Literal, Optional

from pydantic import Field, field_validator

from .base import NacModel

FABRIC_TYPES = ("VXLAN_EVPN", "MSD", "MCFG", "ISN", "External", "eBGP_VXLAN")
FABRIC_NAME_RE = r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"
ASN_RE = re.compile(r"^(?:\d{1,10}|\d{1,5}\.\d{1,5})$")
MAC_RES = [
    re.compile(r"^[a-f0-9]{1}\.[a-f0-9]{1}\.[a-f0-9]{1}$"),
    re.compile(r"^[a-f0-9]{4}\.[a-f0-9]{4}\.[a-f0-9]{4}$"),
    re.compile(r"^[a-f0-9]{2}(?::[a-f0-9]{2}){5}$"),
    re.compile(r"^[a-f0-9]{2}(?:-[a-f0-9]{2}){5}$"),
]


def validate_asn(value) -> str:
    v = str(value).strip()
    if not ASN_RE.match(v):
        raise ValueError("BGP ASN must be plain (65001) or asdot (65000.1)")
    if "." in v:
        hi, lo = (int(x) for x in v.split("."))
        if hi > 65535 or lo > 65535:
            raise ValueError("asdot ASN halves must each be 0-65535")
    elif not 1 <= int(v) <= 4294967295:
        raise ValueError("BGP ASN must be 1-4294967295")
    return v


def validate_mac(value) -> str:
    v = str(value).strip().lower()
    if not any(r.match(v) for r in MAC_RES):
        raise ValueError("MAC must look like 2020.0000.00aa, 20:20:00:00:00:aa or 20-20-00-00-00-aa")
    return v


class Fabric(NacModel):
    name: str = Field(pattern=FABRIC_NAME_RE, description="Starts with a letter; letters, digits, _ and -; max 64")
    type: Literal[FABRIC_TYPES] = "VXLAN_EVPN"


class ManagementServer(NacModel):
    ip_address: IPv4Address | IPv6Address
    vrf: str = "management"


class SyslogServer(ManagementServer):
    severity: int = Field(5, ge=0, le=7)


class GlobalIbgp(NacModel):
    bgp_asn: str
    route_reflectors: Literal[2, 4] = 2
    anycast_gateway_mac: str = "20:20:00:00:00:aa"
    overlay_mode: Optional[Literal["cli", "config-profile"]] = None
    greenfield_cleanup: Optional[Literal["Enable", "Disable"]] = None
    dns_servers: list[ManagementServer] = Field(default_factory=list, max_length=4)
    ntp_servers: list[ManagementServer] = Field(default_factory=list, max_length=4)
    syslog_servers: list[SyslogServer] = Field(default_factory=list, max_length=4)

    @field_validator("bgp_asn", mode="before")
    @classmethod
    def _asn(cls, v):
        return validate_asn(v)

    @field_validator("anycast_gateway_mac", mode="before")
    @classmethod
    def _mac(cls, v):
        return validate_mac(v)
