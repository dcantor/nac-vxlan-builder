"""Run Cisco's nac-validate against the generated files."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
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


def _exe() -> str:
    local = Path(sys.executable).with_name("nac-validate")
    if local.exists():
        return str(local)
    found = shutil.which("nac-validate")
    if not found:
        raise FileNotFoundError("nac-validate is not installed in this environment")
    return found


def validate_dir(path: Path, schema: Path = SCHEMA, strict: bool = True) -> ValidationResult:
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}
    cmd = [_exe(), "-s", str(schema), str(path)] + ([] if strict else ["--non-strict"])
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    out = _ANSI.sub("", (r.stdout + r.stderr)).replace(f"{path}{os.sep}", "").strip()
    return ValidationResult(r.returncode == 0, out, strict)


def nac_validate(p: Project, schema: Path = SCHEMA) -> ValidationResult:
    """Validate the generated files.

    Settings kept from an imported fabric are often outside the bundled (simplified) schema,
    so those projects are validated in non-strict mode: unknown keys are allowed, while
    every key the schema does define is still checked.
    """
    with tempfile.TemporaryDirectory() as d:
        write_host_vars(p, Path(d))
        return validate_dir(Path(d) / "host_vars", schema, strict=p.preserved.is_empty())
