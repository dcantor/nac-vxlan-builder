"""The fabric list: one JSON file per fabric, keyed by a stable ID.

Files live in ~/.nac-vxlan-builder/fabrics/<id>.json (override with NACB_FABRICS_DIR). The ID never
changes, so renaming a fabric keeps it the same fabric, and two fabrics can share a name. Every
change the app makes is saved here straight away; History (history.py) keeps the older versions,
in a folder per fabric ID.

Fabrics saved by older versions of the app only exist as History folders named after the fabric;
`migrate_from_history` turns each one into a fabric (once).
"""

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .models import Project

DEFAULT_ROOT = Path.home() / ".nac-vxlan-builder" / "fabrics"
_MIGRATED = ".migrated-from-history"


def store_root() -> Path:
    return Path(os.environ.get("NACB_FABRICS_DIR") or DEFAULT_ROOT).expanduser()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _counts(p: Project) -> dict:
    return {"switches": len(p.switches), "vpc": len(p.vpc_peers), "interfaces": len(p.interfaces),
            "vrfs": len(p.vrfs), "networks": len(p.networks), "vrf_lites": len(p.vrf_lites)}


@dataclass(frozen=True)
class FabricRecord:
    id: str
    name: str
    standard: str
    updated: datetime
    counts: dict = field(default_factory=dict, compare=False, hash=False)


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else store_root()

    def _path(self, fid: str) -> Path:
        if not fid or not all(c.isalnum() or c in "-_" for c in fid):
            raise ValueError(f"bad fabric id {fid!r}")
        return self.root / f"{fid}.json"

    def exists(self, fid: str | None) -> bool:
        return bool(fid) and self._path(fid).is_file()

    def save(self, fid: str, p: Project, updated: datetime | None = None) -> FabricRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        when = updated or datetime.now()
        data = {"id": fid, "name": p.fabric.name, "standard": p.standard, "updated": when.isoformat(),
                "counts": _counts(p), "project": p.model_dump(mode="json")}
        path = self._path(fid)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)  # never leave a half-written fabric
        return FabricRecord(fid, p.fabric.name, p.standard, when, data["counts"])

    def load(self, fid: str) -> Project:
        data = json.loads(self._path(fid).read_text())
        try:
            return Project.model_validate(data["project"])
        except ValidationError as e:
            raise ValueError(f"fabric {data.get('name', fid)} can't be loaded: {e.error_count()} problem(s)") from e

    def record(self, fid: str) -> FabricRecord:
        data = json.loads(self._path(fid).read_text())
        return FabricRecord(data["id"], data["name"], data.get("standard", "dc"),
                            datetime.fromisoformat(data["updated"]), data.get("counts", {}))

    def list(self) -> list[FabricRecord]:
        """All fabrics, most recently changed first."""
        out = []
        for path in self.root.glob("*.json") if self.root.is_dir() else []:
            try:
                out.append(self.record(path.stem))
            except (OSError, ValueError, KeyError):
                continue  # a broken file shouldn't hide the others
        return sorted(out, key=lambda r: (r.updated, r.id), reverse=True)

    def delete(self, fid: str) -> bool:
        path = self._path(fid)
        if path.is_file():
            path.unlink()
            return True
        return False

    def migrate_from_history(self, history=None) -> int:
        """Once: turn each History folder from older versions (named after a fabric) into a fabric."""
        from .history import History

        marker = self.root / _MIGRATED
        if marker.exists():
            return 0
        h = history or History()
        known = {r.id for r in self.list()}
        n = 0
        for folder in h.fabrics():
            if folder in known:
                continue  # already a per-ID History folder
            snaps = h.list(folder)
            if not snaps:
                continue
            try:
                p = h.load(snaps[0].path)
            except (OSError, ValueError):
                continue
            fid = new_id()
            self.save(fid, p, updated=snaps[0].created)
            try:  # keep its History: the folder is now named after the ID
                (h.root / folder).rename(h.root / fid)
            except OSError:
                pass
            n += 1
        self.root.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{n} fabric(s) migrated\n")
        return n
