"""Per-machine settings (where the full NaC schema and Cisco's validation rules live)."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG = Path.home() / ".nac-vxlan-builder.json"
COLLECTION = Path("ansible_collections/cisco/nac_dc_vxlan")
RULE_SETS = ("common", "common_vxlan", "ibgp_vxlan")  # what the collection runs for an iBGP VXLAN_EVPN fabric


@dataclass
class Settings:
    schema_path: str = ""  # blank = the bundled simplified schema
    rules_path: str = ""  # blank = auto-detect the installed cisco.nac_dc_vxlan collection
    use_rules: bool = True


def load_settings(path: Path = CONFIG) -> Settings:
    try:
        data = json.loads(Path(path).read_text())
        return Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(s: Settings, path: Path = CONFIG) -> None:
    Path(path).write_text(json.dumps(asdict(s), indent=2))


def collection_roots() -> list[Path]:
    """Where Ansible installs collections: ANSIBLE_COLLECTIONS_PATH(S), ~/.ansible, system dirs."""
    roots = []
    for var in ("ANSIBLE_COLLECTIONS_PATH", "ANSIBLE_COLLECTIONS_PATHS"):
        roots += [Path(p).expanduser() for p in os.environ.get(var, "").split(os.pathsep) if p]
    roots += [Path.home() / ".ansible/collections", Path("/usr/share/ansible/collections")]
    return roots


def find_collection_rules() -> Path | None:
    for root in collection_roots():
        rules = root / COLLECTION / "roles/validate/files/rules"
        if rules.is_dir():
            return rules
    return None


def rule_dirs(path: Path) -> list[Path]:
    """The collection's rules folder has one subfolder per fabric type; anything else is used as-is."""
    path = Path(path).expanduser()
    subs = [path / s for s in RULE_SETS if (path / s).is_dir()]
    return subs or ([path] if path.is_dir() else [])


def resolve_rules(s: Settings) -> list[Path]:
    if not s.use_rules:
        return []
    if s.rules_path:
        return rule_dirs(Path(s.rules_path))
    found = find_collection_rules()
    return rule_dirs(found) if found else []
