"""Where the app writes things on disk.

Generated YAML goes to `export/<fabric>/` in the project root by default: the app creates
`export/` on start and a sub folder for each fabric it works on. NACB_EXPORT_DIR overrides the
root (used by the tests).
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def export_root() -> Path:
    return Path(os.environ.get("NACB_EXPORT_DIR") or PROJECT_ROOT / "export").expanduser()


def fabric_export_dir(fabric_name: str, create: bool = True) -> Path:
    """`export/<fabric>/`, created (with `export/`) unless create=False."""
    d = export_root() / fabric_name
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d
