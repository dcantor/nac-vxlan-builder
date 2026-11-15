"""Switch interfaces (`vxlan.topology.switches[].interfaces`) and vPC pairs (`vxlan.topology.vpc_peers`).

Key names follow Cisco's cisco.nac_dc_vxlan collection (0.9.1) templates. Interfaces are stored
flat on the Project with a `switch` field (app-only) and nested under their switch on export.
"""

import re
from ipaddress import IPv4Interface
from typing import Literal, Optional, Union

from pydantic import Field, field_validator, model_validator

from .base import NacModel

ETH_RE = re.compile(r"(?i)^(?:e|eth(?:ernet)?)\d+/\d+(?:/\d+)?$")
PO_RE = re.compile(r"(?i)^(?:po|port-channel)([1-9]\d{0,3})$")
SUB_RE = re.compile(r"(?i)^(?:(?:e|eth(?:ernet)?)\d+/\d+(?:/\d+)?|(?:po|port-channel)[1-9]\d{0,3})\.\d+$")
LO_RE = re.compile(r"(?i)^(?:lo|loopback)\d+$")

MODES = ("access", "trunk", "routed", "routed_po", "routed_sub", "loopback")
SPEEDS = ("auto", "100mb", "1gb", "10gb", "25gb", "40gb", "100gb", "200gb", "400gb", "800gb")


def split_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x for x in re.split(r"[,\s]+", v) if x]
    return [str(x) for x in v]


def parse_vlan_ranges(text: str) -> list[tuple[int, int | None]]:
    """'10-20, 50' -> [(10, 20), (50, None)]; 'all' -> [(1, 4094)]."""
    text = text.strip().lower()
    if text == "all":
        return [(1, 4094)]
    out = []
    for part in [p for p in re.split(r"[,\s]+", text) if p]:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"'{part}' isn't a VLAN or range (use 10-20,50)")
        a, b = int(m[1]), int(m[2]) if m[2] else None
        if not 1 <= a <= 4094 or (b is not None and not a <= b <= 4094):
            raise ValueError(f"VLAN range '{part}' must be within 1-4094, low to high")
        out.append((a, b))
    return out


def vlan_ranges_to_text(items) -> str:
    """NaC list [{from: 10, to: 20}, {from: 50}] -> '10-20,50'."""
    parts = []
    for i in items or []:
        parts.append(f"{i['from']}-{i['to']}" if i.get("to") not in (None, i["from"]) else str(i["from"]))
    return ",".join(parts)


class Interface(NacModel):
    switch: str = Field(min_length=1)  # app-only: which switch the interface belongs to
    name: str = Field(min_length=1)
    mode: Literal[MODES]
    description: Optional[str] = Field(None, max_length=254)
    enabled: Optional[bool] = None
    mtu: Optional[Union[int, Literal["jumbo", "default"]]] = None
    speed: Optional[Literal[SPEEDS]] = None
    access_vlan: Optional[int] = Field(None, ge=1, le=4094)
    trunk_allowed_vlans: Optional[str] = None  # app form "10-20,50"; exported as NaC from/to list
    native_vlan: Optional[int] = Field(None, ge=1, le=4094)
    ipv4_address: Optional[IPv4Interface] = None
    vrf: Optional[str] = None
    dot1q_id: Optional[int] = Field(None, ge=1, le=4093)
    members: list[str] = Field(default_factory=list)
    vpc_id: Optional[int] = Field(None, ge=1, le=4096)
    pc_mode: Optional[Literal["active", "passive", "on"]] = None
    spanning_tree_portfast: Optional[bool] = None
    enable_bpdu_guard: Optional[bool] = None

    @field_validator("members", mode="before")
    @classmethod
    def _members(cls, v):
        members = split_list(v)
        bad = [m for m in members if not ETH_RE.match(m)]
        if bad:
            raise ValueError(f"members must be Ethernet ports, not {', '.join(bad)}")
        return members

    @field_validator("trunk_allowed_vlans", mode="before")
    @classmethod
    def _trunk(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, list):
            v = vlan_ranges_to_text(v)
        parse_vlan_ranges(str(v))
        return re.sub(r"\s+", "", str(v))

    @field_validator("mtu", mode="before")
    @classmethod
    def _mtu(cls, v):
        if isinstance(v, str) and v.strip().isdigit():
            v = int(v)
        if isinstance(v, int) and not 576 <= v <= 9216:
            raise ValueError("MTU must be 576-9216, jumbo or default")
        return v

    @model_validator(mode="after")
    def _by_mode(self):
        name, mode = self.name, self.mode
        is_po = bool(PO_RE.match(name))
        if mode == "routed_sub":
            if not SUB_RE.match(name):
                raise ValueError(f"{name}: a routed_sub interface is named like Ethernet1/49.100")
            if self.dot1q_id is None:
                raise ValueError(f"{name}: routed_sub needs a dot1q_id")
        elif mode == "loopback":
            if not LO_RE.match(name):
                raise ValueError(f"{name}: a loopback is named like loopback10")
        elif mode == "routed_po":
            if not is_po:
                raise ValueError(f"{name}: routed_po needs a port-channel name like port-channel20")
        elif not (ETH_RE.match(name) or is_po):
            raise ValueError(f"{name}: use an Ethernet port (Ethernet1/10) or port-channel (port-channel10)")
        if (is_po or mode == "routed_po") and not self.members:
            raise ValueError(f"{name}: a port-channel needs member ports")
        if self.members and not (is_po or mode == "routed_po"):
            raise ValueError(f"{name}: only port-channels have members")
        if self.vpc_id is not None and not (is_po and mode in ("access", "trunk")):
            raise ValueError(f"{name}: vpc_id is only for access/trunk port-channels")
        if self.access_vlan is not None and mode != "access":
            raise ValueError(f"{name}: access_vlan only applies in access mode")
        if (self.trunk_allowed_vlans or self.native_vlan) and mode != "trunk":
            raise ValueError(f"{name}: allowed/native VLANs only apply in trunk mode")
        if (self.ipv4_address or self.vrf) and mode not in ("routed", "routed_po", "routed_sub", "loopback"):
            raise ValueError(f"{name}: IP address and VRF only apply to routed interfaces")
        if self.dot1q_id is not None and mode != "routed_sub":
            raise ValueError(f"{name}: dot1q_id only applies to routed_sub")
        return self

    @property
    def is_port_channel(self) -> bool:
        return bool(PO_RE.match(self.name)) or self.mode == "routed_po"

    @property
    def key(self) -> str:
        return f"{self.switch}/{self.name}"

    def to_nac(self) -> dict:
        d = super().to_nac()
        d.pop("switch")
        if self.trunk_allowed_vlans:
            d["trunk_allowed_vlans"] = [
                {"from": a, "to": b} if b is not None else {"from": a} for a, b in parse_vlan_ranges(self.trunk_allowed_vlans)
            ]
        return d


class VpcPeer(NacModel):
    peer1: str = Field(min_length=1)
    peer2: str = Field(min_length=1)
    domain_id: Optional[int] = Field(None, ge=1, le=1000)
    fabric_peering: Optional[bool] = None  # virtual peer link over the fabric (no physical peer link)
    peer1_peerlink_interfaces: list[str] = Field(default_factory=list)
    peer2_peerlink_interfaces: list[str] = Field(default_factory=list)

    @field_validator("peer1_peerlink_interfaces", "peer2_peerlink_interfaces", mode="before")
    @classmethod
    def _links(cls, v):
        if isinstance(v, list):
            v = [i["name"] if isinstance(i, dict) else i for i in v]
        names = split_list(v)
        bad = [n for n in names if not ETH_RE.match(n)]
        if bad:
            raise ValueError(f"peer-link members must be Ethernet ports, not {', '.join(bad)}")
        return names

    @model_validator(mode="after")
    def _peers(self):
        if self.peer1 == self.peer2:
            raise ValueError("a vPC pair needs two different switches")
        return self

    @property
    def key(self) -> str:
        return f"{self.peer1}|{self.peer2}"

    def to_nac(self) -> dict:
        d = super().to_nac()
        for k in ("peer1_peerlink_interfaces", "peer2_peerlink_interfaces"):
            if d.get(k):
                d[k] = [{"name": n} for n in d[k]]
        return d
