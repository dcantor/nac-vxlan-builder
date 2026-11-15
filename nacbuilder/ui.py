"""Streamlit helpers shared by the wizard pages.

The Project in session state is the source of truth. Each page edits it inside a
form; on Save the page rebuilds its models, and on success bumps `editor_ver` so
every data_editor restarts from the saved data (otherwise its pending edits would
be re-applied on top of the already-saved rows).
"""

import math
import re
from typing import Callable

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from .checks import Issue, check_project
from .models import Project


def project() -> Project:
    if "project" not in st.session_state:
        st.session_state.project = Project()
    return st.session_state.project


def set_project(p: Project, flash: str | None = None) -> None:
    st.session_state.project = p
    st.session_state.editor_ver = st.session_state.get("editor_ver", 0) + 1
    if flash:
        st.session_state.flash = flash


def save(flash: str | None = None, **changes) -> None:
    set_project(project().model_copy(update=changes), flash)
    st.rerun()


def key(name: str) -> str:
    return f"{name}_{st.session_state.get('editor_ver', 0)}"


def show_flash() -> None:
    if msg := st.session_state.pop("flash", None):
        st.toast(msg, icon="✅")


def clean(v):
    """Normalise a data_editor cell: blanks/NaN -> None, numpy scalars -> Python, 3.0 -> 3."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float):
        if math.isnan(v):
            return None
        if v.is_integer():
            return int(v)
    if isinstance(v, str):
        return v.strip() or None
    return v


def records(df: pd.DataFrame) -> list[dict]:
    rows = [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]
    return [r for r in rows if any(v not in (None, False) for v in r.values())]


def frame(rows: list[dict], columns: dict[str, str]) -> pd.DataFrame:
    """Build a DataFrame with stable column order and dtypes (Int64/string/bool)."""
    df = pd.DataFrame(rows, columns=list(columns))
    for col, dtype in columns.items():
        if dtype == "bool":
            df[col] = df[col].fillna(False).astype(bool)
        else:
            df[col] = df[col].astype(dtype)
    return df


def fmt_errors(e: ValidationError, prefix: str = "") -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = re.sub(r"^Value error, ", "", err["msg"])
        out.append(f"{prefix}{loc + ': ' if loc else ''}{msg}")
    return out


def build_rows(rows: list[dict], fn: Callable[[dict], object], label: str) -> tuple[list, list[str]]:
    items, errors = [], []
    for i, r in enumerate(rows, 1):
        try:
            items.append(fn({k: v for k, v in r.items() if v is not None}))
        except ValidationError as e:
            errors += fmt_errors(e, f"{label} row {i}: ")
        except (ValueError, TypeError) as e:
            errors.append(f"{label} row {i}: {e}")
    return items, errors


def show_errors(errors: list[str]) -> None:
    st.error("Not saved. Fix these and save again:\n\n" + "\n".join(f"- {e}" for e in errors))


def section_issues(section: str) -> None:
    """Show the cross-check findings that belong to this page."""
    issues: list[Issue] = [i for i in check_project(project()) if i.section == section]
    for i in issues:
        (st.error if i.level == "error" else st.warning)(i.message, icon="⛔" if i.level == "error" else "⚠️")
