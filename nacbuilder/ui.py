"""Streamlit helpers shared by the wizard pages.

The Project in session state is the source of truth. Each page edits it inside a
form; on Save the page rebuilds its models, and on success bumps `editor_ver` so
every data_editor restarts from the saved data (otherwise its pending edits would
be re-applied on top of the already-saved rows).
"""

from pathlib import Path
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


def switch_fabric(name: str) -> None:
    """Open another fabric's latest saved state (saving the open one first)."""
    from . import workspace

    cur = project()
    if name == cur.fabric.name:
        return
    workspace.save_current(cur)
    target = workspace.latest(name)
    if target is None:
        raise ValueError(f"no saved state for {name}")
    st.session_state.pop("undo", None)  # undo/redo is per fabric
    st.session_state.pop("task_preview", None)
    st.session_state.pop("pp_selected", None)
    set_project(target, record=False)
    st.session_state.flash = f"Switched to {name}"


def header(p: Project) -> None:
    """Frozen bar at the top of every page: which fabric is open, and a switcher."""
    from . import standards as std
    from . import workspace
    from .checks import check_project
    from .demo import is_demo

    dark = getattr(getattr(st.context, "theme", None), "type", None) == "dark"
    bg, border = ("#0e1117", "#31333f") if dark else ("#ffffff", "#e6e8eb")
    st.markdown(f"""<style>
    [data-testid="stHeader"] {{ background: {bg}; }}  /* so content doesn't show above the bar */
    /* Streamlit wraps the container in a stLayoutWrapper; that wrapper is what can stick */
    [data-testid="stLayoutWrapper"]:has(> .st-key-nacb_header) {{
        position: sticky; top: 3.75rem; z-index: 990; background: {bg};
        border-bottom: 1px solid {border}; padding: 0.4rem 0 0.5rem 0; margin-top: -1rem;
    }}
    </style>""", unsafe_allow_html=True)
    with st.container(key="nacb_header"):
        c1, c2, c3 = st.columns([3, 2, 0.32], vertical_alignment="center")
        issues = check_project(p)
        errs = sum(i.level == "error" for i in issues)
        counts = f"{len(p.switches)} switches" + (f" · {len(p.vrfs)} VRFs · {len(p.networks)} networks" if p.is_vxlan else "")
        demo = " · :orange-badge[:material/slideshow: Demo]" if is_demo(p) else ""
        c1.markdown(f":material/edit_note: Editing fabric **`{p.fabric.name}`**{demo}  \n"
                    f":small[{std.get(p.standard).label} · {counts} · {'⛔' if errs else '✅'} {errs} errors]  \n"
                    f":small[{nac_version_text()}]")
        entries = {e.name: e for e in workspace.fabrics()}
        names = [p.fabric.name, *[n for n in entries if n != p.fabric.name]]

        def label(n):
            if n == p.fabric.name:
                return f"{n} (open)"
            return workspace.describe(entries[n])

        def on_pick():
            pick = st.session_state.get(widget_key)
            if pick and pick != p.fabric.name:
                try:
                    switch_fabric(pick)
                except (ValueError, OSError) as e:
                    st.session_state.flash = f"Couldn't switch: {e}"

        with c3:
            theme_toggle(dark, page_paths())
        widget_key = key(f"fabric_switch_{p.fabric.name}")
        c2.selectbox("Switch fabric", names, index=0, format_func=label, key=widget_key, on_change=on_pick,
                     label_visibility="collapsed", disabled=len(names) < 2,
                     help="Fabrics you've worked on (from History). Switching saves the open fabric first.")


@st.cache_data(ttl=60, show_spinner=False)
def _installed_nac() -> str | None:
    from .settings import collection_version

    return collection_version()


def nac_version_text() -> str:
    """'NaC cisco.nac_dc_vxlan 0.9.1 · ND 4.2', plus the installed collection when it's found."""
    from . import NAC_COLLECTION, NAC_VERSION, ND_VERSION, __version__

    text = f":material/sell: NaC `{NAC_COLLECTION}` {NAC_VERSION} · ND {ND_VERSION} · builder {__version__}"
    installed = _installed_nac()
    if installed and installed != NAC_VERSION:
        text += f" · :orange[installed collection is {installed}]"
    elif installed:
        text += " · installed ✓"
    return text


def theme_toggle(dark: bool, paths: list[str]) -> None:
    """Sun/moon button that flips Streamlit's light/dark theme for this browser.

    Streamlit keeps the viewer's choice in localStorage under `stActiveTheme-<page path>-v2` (as
    "Light"/"Dark"); the button writes it for every page path and reloads, the same as picking the
    theme in Streamlit's own Settings menu.
    """
    import json

    import streamlit.components.v1 as components

    target = "Light" if dark else "Dark"
    icon = "☀️" if dark else "🌙"
    fg, bg, border = ("#fafafa", "#262730", "#4b4d57") if dark else ("#31333f", "#ffffff", "#d5d8de")
    components.html(f"""
<style>
  html, body {{ margin: 0; background: transparent; }}
  button {{ width: 38px; height: 38px; border-radius: 8px; border: 1px solid {border}; background: {bg};
           color: {fg}; font-size: 18px; cursor: pointer; line-height: 1; }}
  button:hover {{ border-color: #ff4b4b; }}
</style>
<button id="t" title="Switch to {target.lower()} mode" aria-label="Switch to {target.lower()} mode">{icon}</button>
<script>
  document.getElementById("t").addEventListener("click", () => {{
    try {{
      const store = window.parent.localStorage;
      const paths = new Set({json.dumps(paths)});
      paths.add(window.parent.location.pathname);
      for (let i = 0; i < store.length; i++) {{  // any page Streamlit already remembered
        const k = store.key(i);
        const m = k && k.match(/^stActiveTheme-(.*)-v2$/);
        if (m) paths.add(m[1]);
      }}
      paths.forEach((p) => store.setItem("stActiveTheme-" + p + "-v2", JSON.stringify("{target}")));
      window.parent.location.reload();
    }} catch (e) {{
      alert("Couldn't switch the theme here: use Settings in Streamlit's ⋮ menu instead.");
    }}
  }});
</script>
""", height=40)


def page_paths() -> list[str]:
    """URL paths of the app's pages ("/", "/switches", ...), so a theme choice covers all of them."""
    import glob
    import os

    names = [os.path.splitext(os.path.basename(x))[0] for x in glob.glob(str(Path(__file__).parent.parent / "views" / "*.py"))]
    return ["/", *sorted(f"/{n}" for n in names)]
