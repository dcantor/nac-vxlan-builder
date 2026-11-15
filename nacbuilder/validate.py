"""Run Cisco's nac-validate against the generated files."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .generate import write_host_vars
from .models import Project

SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "schema.yaml"
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass
class ValidationResult:
    ok: bool
    output: str
    strict: bool = True
    schema: str = "bundled"
    rules: list[str] = field(default_factory=list)  # rule folders that were run


def _exe() -> str:
    local = Path(sys.executable).with_name("nac-validate")
    if local.exists():
        return str(local)
    found = shutil.which("nac-validate")
    if not found:
        raise FileNotFoundError("nac-validate is not installed in this environment")
    return found


def _run(cmd: list[str], path: Path) -> tuple[int, str]:
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, _ANSI.sub("", (r.stdout + r.stderr)).replace(f"{path}{os.sep}", "").strip()


def validate_dir(path: Path, schema: Path = SCHEMA, strict: bool = True, rules: list[Path] | None = None) -> ValidationResult:
    """Schema check, then each rules folder in turn (nac-validate loads one flat folder per run)."""
    base = [_exe(), "-s", str(schema), str(path)] + ([] if strict else ["--non-strict"])
    code, out = _run(base, path)
    outputs = [out] if out else []
    ok = code == 0
    if ok:  # rules assume a schema-valid model
        for d in rules or []:
            code, out = _run(base + ["-r", str(d)], path)
            ok = ok and code == 0
            if out:
                outputs.append(f"[rules: {d.name}]\n{out}")
    return ValidationResult(ok, "\n\n".join(outputs), strict, "bundled" if Path(schema) == SCHEMA else str(schema),
                            [str(d) for d in rules or []])


def nac_validate(p: Project, schema: Path | None = None, rules: list[Path] | None = None) -> ValidationResult:
    """Validate the generated files.

    With the bundled (simplified) schema, fabrics carrying imported settings it doesn't cover are
    checked in non-strict mode: unknown keys are allowed, every key the schema defines is still
    checked. A full schema (from your NaC/collection install) is always used in strict mode.
    `rules` are folders of nac-validate rules, e.g. Cisco's cisco.nac_dc_vxlan validate rules.
    """
    full = schema is not None and Path(schema) != SCHEMA
    strict = full or p.preserved.is_empty()
    with tempfile.TemporaryDirectory() as d:
        write_host_vars(p, Path(d))
        return validate_dir(Path(d) / "host_vars", Path(schema) if full else SCHEMA, strict=strict, rules=rules)
