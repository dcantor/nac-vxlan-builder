"""Streamlit helpers shared by the wizard pages.

The Project in session state is the source of truth. Each page edits it inside a
form; on Save the page rebuilds its models, and on success bumps `editor_ver` so
every data_editor restarts from the saved data (otherwise its pending edits would
be re-applied on top of the already-saved rows).
"""

from typing import Callable

import pandas as pd
import streamlit as st

from .checks import Issue, check_project
from .history import EMPTY, History, UndoStack
from .models import Project
from .tabular import TEMPLATES, build_rows, clean, fmt_errors, import_csv, records, template_csv  # noqa: F401 (re-exported)


TABLE_HELP = (
    "Add a row with the empty line at the bottom (or +). To delete, tick the rows on the left and press Delete or click the trash icon. Changes are kept only after **Save**."
)


def project() -> Project:
    if "project" not in st.session_state:
        st.session_state.project = Project()
    return st.session_state.project


def undo_stack() -> UndoStack:
    if "undo" not in st.session_state:
        st.session_state.undo = UndoStack()
    return st.session_state.undo


LOCKED = "Locked by the design standard (Design standards page)."


def set_project(p: Project, flash: str | None = None, record: bool = True) -> None:
    """Replace the project. Unless record=False (undo/redo), the change is snapshotted to history."""
    if record and p != st.session_state.get("project"):
        stack, hist = undo_stack(), History()
        try:
            if not stack.entries:  # first change this session: remember where we started
                start = st.session_state.get("project") or Project()
                stack.push(EMPTY if start == Project() else str(hist.record(start, "Session start").path), "Session start")
            label = flash or "Change"
            stack.push(str(hist.record(p, label).path), label)
        except OSError as e:  # history is a convenience; never block a save on it
            st.session_state.history_error = str(e)
    st.session_state.project = p
    st.session_state.editor_ver = st.session_state.get("editor_ver", 0) + 1
    if flash:
        st.session_state.flash = flash


def undo() -> None:
    target, label = undo_stack().undo()
    set_project(History.load(target), f"Undid: {label}", record=False)


def redo() -> None:
    target, label = undo_stack().redo()
    set_project(History.load(target), f"Redid: {label}", record=False)


def save(flash: str | None = None, **changes) -> None:
    set_project(project().model_copy(update=changes), flash)
    st.rerun()


def key(name: str) -> str:
    return f"{name}_{st.session_state.get('editor_ver', 0)}"


def show_flash() -> None:
    if msg := st.session_state.pop("flash", None):
        st.toast(msg, icon="✅")


def frame(rows: list[dict], columns: dict[str, str]) -> pd.DataFrame:
    """Build a DataFrame with stable column order and dtypes (Int64/string/bool)."""
    df = pd.DataFrame(rows, columns=list(columns))
    for col, dtype in columns.items():
        if dtype == "bool":
            df[col] = pd.Series([bool(clean(v)) for v in df[col]], index=df.index, dtype=bool)
        else:
            df[col] = df[col].astype(dtype)
    return df


def show_errors(errors: list[str], title: str = "Not saved. Fix these and save again:") -> None:
    st.error(f"{title}\n\n" + "\n".join(f"- {e}" for e in errors))


def csv_import(name: str, field: str, columns: dict[str, str], from_row: Callable[[dict], object], required: list[str]) -> None:
    """Expander with a template download and an uploader that replaces or appends `project().<field>`."""
    with st.expander("Import CSV", icon=":material/upload_file:"):
        optional = [c for c in columns if c not in required]
        st.caption(
            f"**Required:** {', '.join(f'`{c}`' for c in required)} · **Optional:** {', '.join(f'`{c}`' for c in optional)}. "
            "Headers are matched case-insensitively; blank cells mean \"not set\"."
        )
        c1, c2 = st.columns([1, 2], vertical_alignment="center")
        c1.download_button(
            "Download template",
            template_csv(list(columns), TEMPLATES[name]),
            file_name=f"{name}_template.csv",
            mime="text/csv",
            icon=":material/download:",
        )
        mode = c2.radio("Imported rows", ["Replace the table", "Append to the table"], horizontal=True, key=f"{name}_csv_mode")
        up = st.file_uploader("CSV file", type=["csv"], key=key(f"{name}_csv"))
        if up is not None:
            items, errors = import_csv(up.getvalue(), list(columns), from_row)
            if errors:
                show_errors(errors, f"Nothing imported from {up.name}. Fix the file and upload it again:")
            else:
                current = getattr(project(), field)
                new = items if mode.startswith("Replace") else [*current, *items]
                verb = "Replaced the table with" if mode.startswith("Replace") else "Appended"
                label = {"vpc": "vPC pair(s)"}.get(name, name)
                save(f"{verb} {len(items)} {label} from {up.name}", **{field: new})


def section_issues(section: str) -> None:
    """Show the cross-check findings that belong to this page."""
    issues: list[Issue] = [i for i in check_project(project()) if i.section == section]
    for i in issues:
        (st.error if i.level == "error" else st.warning)(i.message, icon="⛔" if i.level == "error" else "⚠️")
