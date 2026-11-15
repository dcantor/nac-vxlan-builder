"""Test rule (written for this project) in nac-validate's rule format."""


class Rule:
    id = "900"
    description = "Switch names must be lowercase"
    severity = "LOW"

    @classmethod
    def match(cls, data):
        switches = (data.get("vxlan", {}).get("topology", {}) or {}).get("switches") or []
        return [f"vxlan.topology.switches.{s['name']}" for s in switches if s["name"] != s["name"].lower()]
