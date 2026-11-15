"""The fabrics you can switch between: every fabric with saved history.

Each change to a fabric is snapshotted (history.py), so a fabric's latest snapshot is its current
state. Switching saves the open fabric first (if it changed since its last snapshot) and opens the
latest snapshot of the other one.
"""

from dataclasses import dataclass
from datetime import datetime

from .history import History
from .models import Project


@dataclass(frozen=True)
class FabricEntry:
    name: str
    updated: datetime
    counts: dict
    label: str  # what the last change was
    snapshot_id: str = ""  # sortable to the microsecond (created is to the second)


def fabrics(history: History | None = None) -> list[FabricEntry]:
    """Fabrics with at least one snapshot, most recently changed first."""
    h = history or History()
    out = []
    for name in h.fabrics():
        snaps = h.list(name)
        if snaps:
            out.append(FabricEntry(snaps[0].fabric, snaps[0].created, snaps[0].counts, snaps[0].label, snaps[0].id))
    return sorted(out, key=lambda e: (e.updated, e.snapshot_id), reverse=True)


def latest(name: str, history: History | None = None) -> Project | None:
    h = history or History()
    snaps = h.list(name)
    return h.load(snaps[0].path) if snaps else None


def save_current(p: Project, history: History | None = None) -> bool:
    """Snapshot the open fabric if it differs from its latest snapshot. Returns True if it saved one."""
    h = history or History()
    if p == Project() or latest(p.fabric.name, h) == p:
        return False
    h.record(p, "Saved before switching fabric")
    return True


def describe(e: FabricEntry) -> str:
    c = e.counts or {}
    bits = [f"{c.get('switches', 0)} switches"]
    if c.get("vrfs"):
        bits.append(f"{c['vrfs']} VRFs")
    return f"{e.name} · {', '.join(bits)} · changed {e.updated:%b %d %H:%M}"


def delete_fabric(name: str, history: History | None = None) -> list[str]:
    """Delete a fabric: all its History snapshots and its export/<name>/ folder. Returns what went."""
    import shutil

    from .history import _safe
    from .paths import export_root

    h = history or History()
    removed = []
    n = h.clear(name)
    folder = h.root / _safe(name)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    if n:
        removed.append(f"{n} history snapshot(s)")
    out = export_root() / name
    if out.is_dir() and out.resolve().parent == export_root().resolve():  # never outside export/
        shutil.rmtree(out)
        removed.append(f"export/{name}/")
    return removed
