"""The fabrics you can switch between, on top of the fabric store (store.py).

Each fabric has a stable ID, so renaming keeps it the same fabric and two fabrics can share a
name. Deleting a fabric removes it from the store, its History folder, and its export/<name>/
folder unless another fabric still uses that name.
"""

import shutil

from .history import History, _safe
from .paths import export_root
from .store import FabricRecord, Store


def fabrics(store: Store | None = None) -> list[FabricRecord]:
    """Every fabric, most recently changed first (older History-only fabrics are migrated first)."""
    s = store or Store()
    s.migrate_from_history()
    return s.list()


def describe(r: FabricRecord, all_records: list[FabricRecord] | None = None) -> str:
    """'dc1 · 14 switches, 1 VRFs · changed Nov 15 18:31' (plus the ID when the name is shared)."""
    c = r.counts or {}
    bits = [f"{c.get('switches', 0)} switches"]
    if c.get("vrfs"):
        bits.append(f"{c['vrfs']} VRFs")
    twin = all_records and sum(x.name == r.name for x in all_records) > 1
    return f"{r.name}{f' [{r.id[:6]}]' if twin else ''} · {', '.join(bits)} · changed {r.updated:%b %d %H:%M}"


def delete_fabric(fid: str, store: Store | None = None, history: History | None = None) -> list[str]:
    """Delete a fabric: its store entry, its History snapshots, and export/<name>/ unless another
    fabric has the same name. Returns what was removed."""
    s, h = store or Store(), history or History()
    removed = []
    name = s.record(fid).name if s.exists(fid) else None
    if s.delete(fid):
        removed.append("the fabric")
    n = h.clear(fid)
    folder = h.root / _safe(fid)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    if n:
        removed.append(f"{n} history snapshot(s)")
    if name and not any(r.name == name for r in s.list()):
        out = export_root() / name
        if out.is_dir() and out.resolve().parent == export_root().resolve():  # never outside export/
            shutil.rmtree(out)
            removed.append(f"export/{name}/")
    return removed
