"""Project history: a JSON snapshot each time the project changes, plus a session undo/redo stack.

Snapshots live in ~/.nac-vxlan-builder/history/<fabric>/ (override with NACB_HISTORY_DIR), so you
can step back after a bad bulk edit even after restarting the app.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .models import Project

DEFAULT_ROOT = Path.home() / ".nac-vxlan-builder" / "history"
KEEP = 200  # snapshots per fabric
EMPTY = ""  # undo-stack entry meaning "a new, empty project"


def history_root() -> Path:
    return Path(os.environ.get("NACB_HISTORY_DIR") or DEFAULT_ROOT).expanduser()


@dataclass(frozen=True)
class Snapshot:
    path: Path
    fabric: str
    label: str
    created: datetime
    counts: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def id(self) -> str:
        return self.path.stem


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "fabric"


def _counts(p: Project) -> dict:
    return {"switches": len(p.switches), "vpc": len(p.vpc_peers), "interfaces": len(p.interfaces),
            "vrfs": len(p.vrfs), "networks": len(p.networks), "vrf_lites": len(p.vrf_lites)}


class History:
    def __init__(self, root: Path | None = None, keep: int = KEEP):
        self.root = Path(root) if root else history_root()
        self.keep = keep

    def record(self, p: Project, label: str) -> Snapshot:
        folder = self.root / _safe(p.fabric.name)
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = folder / f"{now:%Y%m%d-%H%M%S-%f}.json"
        n = 1
        while path.exists():  # same microsecond (fast tests)
            path, n = folder / f"{now:%Y%m%d-%H%M%S-%f}-{n}.json", n + 1
        path.write_text(json.dumps({
            "label": label, "created": now.isoformat(timespec="seconds"), "counts": _counts(p),
            "project": p.model_dump(mode="json"),
        }))
        self._prune(folder)
        return self._read_meta(path)

    def _prune(self, folder: Path) -> None:
        files = sorted(folder.glob("*.json"))
        for old in files[: max(0, len(files) - self.keep)]:
            old.unlink()

    def _read_meta(self, path: Path) -> Snapshot:
        data = json.loads(path.read_text())
        return Snapshot(path, path.parent.name, data.get("label", ""), datetime.fromisoformat(data["created"]),
                        data.get("counts", {}))

    def fabrics(self) -> list[str]:
        return sorted(d.name for d in self.root.iterdir() if d.is_dir()) if self.root.is_dir() else []

    def list(self, fabric: str) -> list[Snapshot]:
        """Newest first."""
        folder = self.root / _safe(fabric)
        out = []
        for path in sorted(folder.glob("*.json"), reverse=True) if folder.is_dir() else []:
            try:
                out.append(self._read_meta(path))
            except (OSError, ValueError, KeyError):
                continue
        return out

    @staticmethod
    def load(path: Path | str) -> Project:
        if path == EMPTY:
            return Project()
        data = json.loads(Path(path).read_text())
        try:
            return Project.model_validate(data["project"])
        except ValidationError as e:
            raise ValueError(f"snapshot {Path(path).name} can't be loaded: {e.error_count()} problem(s)") from e

    def clear(self, fabric: str) -> int:
        folder = self.root / _safe(fabric)
        files = list(folder.glob("*.json")) if folder.is_dir() else []
        for f in files:
            f.unlink()
        return len(files)


@dataclass
class UndoStack:
    """Snapshot paths in order; `pos` is the one matching the current project."""

    entries: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    pos: int = -1

    def push(self, entry: str, label: str) -> None:
        self.entries = self.entries[: self.pos + 1] + [entry]
        self.labels = self.labels[: self.pos + 1] + [label]
        self.pos = len(self.entries) - 1

    @property
    def can_undo(self) -> bool:
        return self.pos > 0

    @property
    def can_redo(self) -> bool:
        return self.pos < len(self.entries) - 1

    def undo(self) -> tuple[str, str]:
        """Step back; returns (snapshot to restore, label of the change being undone)."""
        if not self.can_undo:
            raise IndexError("nothing to undo")
        undone = self.labels[self.pos]
        self.pos -= 1
        return self.entries[self.pos], undone

    def redo(self) -> tuple[str, str]:
        if not self.can_redo:
            raise IndexError("nothing to redo")
        self.pos += 1
        return self.entries[self.pos], self.labels[self.pos]
