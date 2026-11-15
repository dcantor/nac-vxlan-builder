"""Settings found in imported YAML that this app doesn't model.

They are kept verbatim and merged back into the generated files, so importing a fabric,
editing it here and writing it back never drops configuration the app doesn't know about
(interfaces, vPC peers, policies, extra VRF/network options, ...).
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

_DATA_FIELDS = (
    "fabric",
    "global_extra",
    "ibgp",
    "topology",
    "underlay",
    "overlay",
    "other",
    "switches",
    "vrfs",
    "networks",
    "attach",
    "attach_groups",
)


class Preserved(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Optional[str] = None  # folder or upload the fabric was imported from
    files: list[str] = Field(default_factory=list)  # imported file paths, relative to the fabric folder

    fabric: dict[str, Any] = Field(default_factory=dict)  # unknown keys in vxlan.fabric
    global_extra: dict[str, Any] = Field(default_factory=dict)  # vxlan.global keys other than ibgp
    ibgp: dict[str, Any] = Field(default_factory=dict)  # unknown keys in vxlan.global.ibgp
    topology: dict[str, Any] = Field(default_factory=dict)  # vxlan.topology other than switches
    underlay: dict[str, Any] = Field(default_factory=dict)  # unknown underlay keys/sections (nested)
    overlay: dict[str, Any] = Field(default_factory=dict)  # vxlan.overlay other than vrfs/networks/groups
    other: dict[str, Any] = Field(default_factory=dict)  # other vxlan.* sections (policy, multisite, ...)
    switches: dict[str, dict[str, Any]] = Field(default_factory=dict)  # by switch name
    vrfs: dict[str, dict[str, Any]] = Field(default_factory=dict)  # by VRF name
    networks: dict[str, dict[str, Any]] = Field(default_factory=dict)  # by network name
    attach: dict[str, dict[str, Any]] = Field(default_factory=dict)  # "vrf|network/<group>/<hostname>"
    attach_groups: dict[str, dict[str, Any]] = Field(default_factory=dict)  # "vrf|network/<group>"

    def is_empty(self) -> bool:
        return not any(getattr(self, f) for f in _DATA_FIELDS)

    def summary(self) -> list[str]:
        """Human-readable list of what is being carried through."""
        out = []

        def keys(d: dict) -> str:
            return ", ".join(f"`{k}`" for k in d)

        if self.fabric:
            out.append(f"Fabric: {keys(self.fabric)}")
        if self.global_extra:
            out.append(f"Global: {keys(self.global_extra)}")
        if self.ibgp:
            out.append(f"Global iBGP: {keys(self.ibgp)}")
        if self.underlay:
            out.append(f"Underlay: {keys(self.underlay)}")
        if self.topology:
            out.append(f"Topology: {keys(self.topology)}")
        if self.overlay:
            out.append(f"Overlay: {keys(self.overlay)}")
        if self.other:
            out.append(f"Other sections: {keys(self.other)}")
        for label, items in (("switch", self.switches), ("VRF", self.vrfs), ("network", self.networks)):
            if items:
                fields = sorted({k for d in items.values() for k in d})
                out.append(f"{len(items)} {label}(s): {', '.join(f'`{k}`' for k in fields)}")
        if self.attach or self.attach_groups:
            out.append(f"Attach groups: {len(self.attach) + len(self.attach_groups)} extra setting(s)")
        return out
