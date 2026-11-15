"""Per-machine settings (where the full NaC schema and Cisco's validation rules live)."""

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG = Path.home() / ".nac-vxlan-builder.json"
COLLECTION = Path("ansible_collections/cisco/nac_dc_vxlan")
# What the collection's own validator runs per fabric type (plugins/action/common/nac_dc_validate.py).
RULE_SETS_BY_TYPE = {
    "VXLAN_EVPN": ("common", "ibgp_vxlan", "common_vxlan"),
    "External": ("common", "external"),
}
RULE_SETS = RULE_SETS_BY_TYPE["VXLAN_EVPN"]


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


def rule_dirs(path: Path, fabric_type: str = "VXLAN_EVPN") -> list[Path]:
    """The collection's rules folder has one subfolder per fabric type; anything else is used as-is."""
    path = Path(path).expanduser()
    sets = RULE_SETS_BY_TYPE.get(fabric_type, RULE_SETS)
    subs = [path / s for s in sets if (path / s).is_dir()]
    if any((path / x).is_dir() for xs in RULE_SETS_BY_TYPE.values() for x in xs):
        return subs  # it's the collection's rules folder: only this fabric type's sets
    return [path] if path.is_dir() else []


def resolve_rules(s: Settings, platform: str | None = None, fabric_type: str = "VXLAN_EVPN") -> list[Path]:
    if not s.use_rules or not rules_supported(platform):
        return []
    if s.rules_path:
        return rule_dirs(Path(s.rules_path), fabric_type)
    found = find_collection_rules()
    return rule_dirs(found, fabric_type) if found else []


# --- platform support for Cisco's rules ------------------------------------------------
# Cisco's rules come with the cisco.nac_dc_vxlan Ansible collection. Ansible's control node doesn't run
# natively on Windows, so the rules (and the one-click install) are offered on macOS only.
ANSIBLE_SPEC = "ansible-core>=2.14,<2.19"
COLLECTION_NAME = "cisco.nac_dc_vxlan"


def is_macos(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "darwin"


def is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform).startswith(("win", "cygwin", "msys"))


def rules_supported(platform: str | None = None) -> bool:
    return is_macos(platform)


def collection_version(rules: Path | None = None) -> str | None:
    """Installed cisco.nac_dc_vxlan version, read from its MANIFEST.json."""
    rules = rules or find_collection_rules()
    if not rules:
        return None
    try:
        manifest = Path(rules).parents[3] / "MANIFEST.json"
        return json.loads(manifest.read_text())["collection_info"]["version"]
    except (OSError, ValueError, KeyError, IndexError):
        return None


@dataclass
class InstallResult:
    ok: bool
    log: str


def install_cisco_rules(timeout: int = 900) -> InstallResult:
    """pip-install ansible-core into this environment, then `ansible-galaxy collection install cisco.nac_dc_vxlan`
    (into ~/.ansible/collections, where the app looks for it). macOS only."""
    if not rules_supported():
        return InstallResult(False, "Cisco's rules are only offered when the app runs on macOS.")
    steps = [
        [sys.executable, "-m", "pip", "install", ANSIBLE_SPEC],
        [str(Path(sys.executable).with_name("ansible-galaxy")), "collection", "install", COLLECTION_NAME],
    ]
    log = []
    for cmd in steps:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.append(f"$ {' '.join(cmd[-3:])}\n{e}")
            return InstallResult(False, "\n\n".join(log))
        out = (r.stdout + r.stderr).strip().splitlines()
        log.append(f"$ {' '.join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd))}\n" + "\n".join(out[-15:]))
        if r.returncode != 0:
            return InstallResult(False, "\n\n".join(log))
    return InstallResult(find_collection_rules() is not None, "\n\n".join(log))
