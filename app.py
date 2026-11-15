"""NaC VXLAN Builder: run with `streamlit run app.py`."""

import streamlit as st
from pydantic import ValidationError

from nacbuilder.checks import check_project
from nacbuilder.models import Project
from nacbuilder.sample import standard_example
from nacbuilder.ui import key, project, set_project, show_flash

st.set_page_config(page_title="NaC VXLAN Builder", page_icon=":material/lan:", layout="wide")

pages = [
    st.Page("views/import_yaml.py", title="Import YAML", icon=":material/upload_file:"),
    st.Page("views/fabric.py", title="1. Fabric", icon=":material/hub:", default=True),
    st.Page("views/switches.py", title="2. Switches", icon=":material/dns:"),
    st.Page("views/underlay.py", title="3. Underlay", icon=":material/route:"),
    st.Page("views/attach.py", title="4. Attach groups", icon=":material/group_work:"),
    st.Page("views/vrfs.py", title="5. VRFs", icon=":material/account_tree:"),
    st.Page("views/networks.py", title="6. Networks", icon=":material/lan:"),
    st.Page("views/review.py", title="7. Review & export", icon=":material/download:"),
]
nav = st.navigation(pages)

p = project()
with st.sidebar:
    st.markdown(f"**Fabric:** `{p.fabric.name}` · {len(p.switches)} switches · {len(p.vrfs)} VRFs · {len(p.networks)} networks")
    issues = check_project(p)
    errs = sum(i.level == "error" for i in issues)
    warns = len(issues) - errs
    st.caption(f"{'⛔' if errs else '✅'} {errs} errors · ⚠️ {warns} warnings")
    st.page_link(pages[-1], label="Review issues and export")

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
