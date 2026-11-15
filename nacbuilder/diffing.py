"""What writing a fabric to a folder would change: per-file text diffs and an item-level summary."""

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .generate import plan_write, render_all
from .importer import import_folder
from .models import Project


@dataclass
class FileDiff:
    name: str
    status: Literal["new", "changed", "unchanged", "removed"]
    diff: str = ""
    added: int = 0
    removed: int = 0


@dataclass
class ChangeSummary:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _count(diff_lines: list[str]) -> tuple[int, int]:
    plus = sum(1 for d in diff_lines if d.startswith("+") and not d.startswith("+++"))
    minus = sum(1 for d in diff_lines if d.startswith("-") and not d.startswith("---"))
    return plus, minus


def file_diffs(p: Project, dest: Path, remove_stale: bool = True) -> list[FileDiff]:
    """Unified diff of each generated file against what's on disk (plus superseded files, if removed)."""
    dest = Path(dest).expanduser()
    out = []
    for name, text in render_all(p).items():
        path = dest / name
        old = path.read_text(encoding="utf-8") if path.is_file() else None
        if old == text:
            out.append(FileDiff(name, "unchanged"))
            continue
        lines = list(difflib.unified_diff(
            (old or "").splitlines(keepends=True), text.splitlines(keepends=True),
            fromfile=f"a/{name}" if old is not None else "/dev/null", tofile=f"b/{name}", n=3,
        ))
        plus, minus = _count(lines)
        out.append(FileDiff(name, "changed" if old is not None else "new", "".join(lines), plus, minus))
    if remove_stale:
        for rel in plan_write(p, dest).stale:
            old = (dest / rel).read_text(encoding="utf-8", errors="replace")
            lines = list(difflib.unified_diff(old.splitlines(keepends=True), [], fromfile=f"a/{rel}", tofile="/dev/null"))
            out.append(FileDiff(rel, "removed", "".join(lines), 0, _count(lines)[1]))
    return out


def project_diffs(old: Project, new: Project, context: int = 3) -> list[FileDiff]:
    """Unified diff of each generated YAML file going from `old` to `new` (e.g. a Day-2 preview).
    Files only one side generates show as new or removed."""
    before, after = render_all(old), render_all(new)
    out = []
    for name in list(dict.fromkeys([*before, *after])):
        a, b = before.get(name), after.get(name)
        if a == b:
            out.append(FileDiff(name, "unchanged"))
            continue
        lines = list(difflib.unified_diff(
            (a or "").splitlines(keepends=True), (b or "").splitlines(keepends=True),
            fromfile=f"a/{name}" if a is not None else "/dev/null",
            tofile=f"b/{name}" if b is not None else "/dev/null", n=context,
        ))
        plus, minus = _count(lines)
        status = "new" if a is None else "removed" if b is None else "changed"
        out.append(FileDiff(name, status, "".join(lines), plus, minus))
    return out


def _items(p: Project) -> dict[str, dict[str, object]]:
    return {
        "switch": {s.name: s.to_nac() for s in p.switches},
        "vPC pair": {v.key.replace("|", " + "): v.to_nac() for v in p.vpc_peers},
        "interface": {f"{i.switch} {i.name}": i.to_nac() for i in p.interfaces},
        "VRF": {v.name: v.to_nac() for v in p.vrfs},
        "network": {n.name: n.to_nac() for n in p.networks},
        "attach group": {
            g: sorted((a.hostname, a.used_for, tuple(a.ports)) for a in rows) for g, rows in p.attach_groups().items()
        },
        "VRF-lite": {v.name: v.to_nac() for v in p.vrf_lites},
        "setting": {
            "fabric": p.fabric.to_nac(),
            "global iBGP": p.ibgp.to_nac(),
            "underlay": p.underlay.to_nac(),
        },
    }


def change_summary(p: Project, dest: Path) -> ChangeSummary | None:
    """Added/removed/changed items compared with the fabric currently in `dest` (None if there isn't one)."""
    dest = Path(dest).expanduser()
    if not dest.is_dir():
        return None
    current = import_folder(dest)
    if current.project is None:
        return None
    return compare_projects(current.project, p)


def compare_projects(old: Project, new: Project) -> ChangeSummary:
    """Items added, removed or changed going from `old` to `new`."""
    before, after = _items(old), _items(new)
    out = ChangeSummary()
    for kind in after:
        b, a = before[kind], after[kind]
        out.added += [f"{kind} {k}" for k in a if k not in b]
        out.removed += [f"{kind} {k}" for k in b if k not in a]
        out.changed += [f"{kind} {k}" for k in a if k in b and a[k] != b[k]]
    return out
