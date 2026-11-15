"""NaC VXLAN Builder: run with `streamlit run app.py`."""

import streamlit as st
from pydantic import ValidationError

from nacbuilder import paths
from nacbuilder import standards as std
from nacbuilder.checks import check_project
from nacbuilder.models import Project
from nacbuilder.sample import standard_example
from nacbuilder.ui import key, project, redo, set_project, show_flash, undo, undo_stack

st.set_page_config(page_title="NaC VXLAN Builder", page_icon=":material/lan:", layout="wide")

p = project()
try:  # export/ in the project root, with a sub folder per fabric
    export_dir = paths.fabric_export_dir(p.fabric.name)
except OSError:
    export_dir = None
# (file, title, icon, VXLAN-only?) in wizard order; numbered after filtering for the fabric's standard.
STEPS = [
    ("views/fabric.py", "Fabric", ":material/hub:", False),
    ("views/switches.py", "Switches", ":material/dns:", False),
    ("views/vpc.py", "vPC pairs", ":material/link:", False),
    ("views/underlay.py", "Underlay", ":material/route:", True),
    ("views/interfaces.py", "Interfaces", ":material/settings_ethernet:", False),
    ("views/attach.py", "Attach groups", ":material/group_work:", True),
    ("views/vrfs.py", "VRFs", ":material/account_tree:", True),
    ("views/networks.py", "Networks", ":material/lan:", True),
    ("views/vrf_lite.py", "VRF-lite", ":material/alt_route:", True),
    ("views/topology.py", "Topology", ":material/schema:", False),
    ("views/cabling.py", "Cabling plan", ":material/cable:", False),
    ("views/review.py", "Review & export", ":material/download:", False),
]
steps = [s for s in STEPS if p.is_vxlan or not s[3]]
pages = [
    st.Page("views/import_yaml.py", title="Import YAML", icon=":material/upload_file:"),
    *[st.Page(path, title=f"{n}. {title}", icon=icon, default=(path == "views/fabric.py"))
      for n, (path, title, icon, _) in enumerate(steps, 1)],
]
history_page = st.Page("views/history.py", title="History", icon=":material/history:")
standards_page = st.Page("views/standards_editor.py", title="Design standards (dev)", icon=":material/developer_mode:")
tasks_page = st.Page("views/tasks.py", title="Day-2 tasks", icon=":material/task_alt:")
nav = st.navigation([*pages, history_page, standards_page, tasks_page], expanded=True)  # show all, Day-2 last

with st.sidebar:
    counts = f"{len(p.switches)} switches" + (f" · {len(p.vrfs)} VRFs · {len(p.networks)} networks" if p.is_vxlan else "")
    st.markdown(f"**Fabric:** `{p.fabric.name}` · {std.get(p.standard).label} · {counts}")
    if export_dir:
        st.caption(f"Export folder: `export/{p.fabric.name}/`")
    issues = check_project(p)
    errs = sum(i.level == "error" for i in issues)
    warns = len(issues) - errs
    st.caption(f"{'⛔' if errs else '✅'} {errs} errors · ⚠️ {warns} warnings")
    st.page_link(pages[-1], label="Review issues and export")

    stack = undo_stack()
    c1, c2 = st.columns(2)
    if c1.button("Undo", icon=":material/undo:", disabled=not stack.can_undo, use_container_width=True,
                 help=f"Undo: {stack.labels[stack.pos]}" if stack.can_undo else "Nothing to undo"):
        try:
            undo()
        except (ValueError, OSError) as e:
            st.error(f"Couldn't undo: {e}")
        st.rerun()
    if c2.button("Redo", icon=":material/redo:", disabled=not stack.can_redo, use_container_width=True,
                 help=f"Redo: {stack.labels[stack.pos + 1]}" if stack.can_redo else "Nothing to redo"):
        try:
            redo()
        except (ValueError, OSError) as e:
            st.error(f"Couldn't redo: {e}")
        st.rerun()
    st.page_link(history_page, label="History", icon=":material/history:")

    st.divider()
    st.markdown("**Project**")
    st.download_button(
        "Save project (.json)",
        p.model_dump_json(indent=2),
        file_name=f"{p.fabric.name}.nacproj.json",
        mime="application/json",
        use_container_width=True,
    )
    up = st.file_uploader("Load project", type=["json"], key=key("project_upload"))
    if up is not None:
        try:
            set_project(Project.model_validate_json(up.getvalue()), f"Loaded {up.name}")
            st.rerun()
        except ValidationError as e:
            st.error(f"Not a valid project file: {e.error_count()} problem(s)")
    c1, c2 = st.columns(2)
    if c1.button("Load example", help="A small fabric that follows the design standard", use_container_width=True):
        set_project(standard_example(), "Loaded the example fabric")
        st.rerun()
    with c2.popover("New", use_container_width=True):
        st.write("Discard the current project and start a new one from a standard's defaults?")
        new_std = st.selectbox("Design standard", list(std.KEYS), format_func=lambda k: std.get(k).label, key="new_std")
        if st.button("Yes, start over", type="primary"):
            set_project(std.new_project(new_std), f"Started a new {std.get(new_std).label} project")
            st.rerun()

show_flash()
nav.run()
