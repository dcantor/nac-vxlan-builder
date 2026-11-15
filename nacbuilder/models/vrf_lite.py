"""VRF-lite handoffs (`vxlan.overlay_extensions.vrf_lites`), eBGP flavour.

Each profile extends one VRF out of the fabric on some border switches: per switch, the routed
sub-interfaces that carry it and the eBGP neighbors on the far side. The sub-interfaces
themselves (dot1q, IP, VRF) live in the topology interfaces.
"""

from ipaddress import IPv4Address
from typing import Optional

from pydantic import Field, field_validator

from .base import NacModel
from .interfaces import SUB_RE, ETH_RE, PO_RE, split_list
from .overlay import NAME_RE


class VrfLitePeer(NacModel):
    address: IPv4Address
    remote_as: int = Field(ge=1, le=4294967295)
    description: Optional[str] = Field(None, max_length=254)


class VrfLiteSwitch(NacModel):
    name: str = Field(min_length=1)
    interfaces: list[str] = Field(default_factory=list)
    bgp_peers: list[VrfLitePeer] = Field(default_factory=list)

    @field_validator("interfaces", mode="before")
    @classmethod
    def _ifs(cls, v):
        if isinstance(v, list):
            v = [i["name"] if isinstance(i, dict) else i for i in v]
        names = split_list(v)
        bad = [n for n in names if not (SUB_RE.match(n) or ETH_RE.match(n) or PO_RE.match(n))]
        if bad:
            raise ValueError(f"invalid VRF-lite interface(s): {', '.join(bad)}")
        return names

    def to_nac(self) -> dict:
        d = super().to_nac()
        if d.get("interfaces"):
            d["interfaces"] = [{"name": n} for n in d["interfaces"]]
        return d


class VrfLite(NacModel):
    name: str = Field(min_length=1, max_length=64, pattern=NAME_RE)
    vrf: str = Field(min_length=1)
    switches: list[VrfLiteSwitch] = Field(default_factory=list)

    def to_nac(self) -> dict:
        return {"name": self.name, "vrf": self.vrf, "switches": [s.to_nac() for s in self.switches]}
