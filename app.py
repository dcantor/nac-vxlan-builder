"""NaC VXLAN Builder: run with `streamlit run app.py`."""

import streamlit as st
from pydantic import ValidationError

from nacbuilder.checks import check_project
from nacbuilder.models import Project
from nacbuilder.sample import standard_example
from nacbuilder.ui import key, project, redo, set_project, show_flash, undo, undo_stack

st.set_page_config(page_title="NaC VXLAN Builder", page_icon=":material/lan:", layout="wide")

pages = [
    st.Page("views/import_yaml.py", title="Import YAML", icon=":material/upload_file:"),
    st.Page("views/tasks.py", title="Day-2 tasks", icon=":material/task_alt:"),
    st.Page("views/fabric.py", title="1. Fabric", icon=":material/hub:", default=True),
    st.Page("views/switches.py", title="2. Switches", icon=":material/dns:"),
    st.Page("views/vpc.py", title="3. vPC pairs", icon=":material/link:"),
    st.Page("views/underlay.py", title="4. Underlay", icon=":material/route:"),
    st.Page("views/interfaces.py", title="5. Interfaces", icon=":material/settings_ethernet:"),
    st.Page("views/attach.py", title="6. Attach groups", icon=":material/group_work:"),
    st.Page("views/vrfs.py", title="7. VRFs", icon=":material/account_tree:"),
    st.Page("views/networks.py", title="8. Networks", icon=":material/lan:"),
    st.Page("views/vrf_lite.py", title="9. VRF-lite", icon=":material/alt_route:"),
    st.Page("views/topology.py", title="10. Topology", icon=":material/schema:"),
    st.Page("views/cabling.py", title="11. Cabling plan", icon=":material/cable:"),
    st.Page("views/review.py", title="12. Review & export", icon=":material/download:"),
]
history_page = st.Page("views/history.py", title="History", icon=":material/history:")
nav = st.navigation([*pages, history_page])

p = project()
with st.sidebar:
    st.markdown(f"**Fabric:** `{p.fabric.name}` · {len(p.switches)} switches · {len(p.vrfs)} VRFs · {len(p.networks)} networks")
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
        st.write("Discard the current project?")
        if st.button("Yes, start over", type="primary"):
            set_project(Project(), "Started a new project")
            st.rerun()

show_flash()
nav.run()
