from pathlib import Path

import streamlit as st

from nacbuilder.checks import check_project
from nacbuilder.importer import ImportResult, find_fabric_dirs, import_folder, import_uploads
from nacbuilder.ui import key, project, set_project

st.title("Import YAML")
st.caption(
    "Load an existing fabric's NaC files (`host_vars/<fabric>/*.nac.yaml`) to add, change or delete its switches, "
    "VRFs and networks here, then write it back from **Review & export**."
)
st.info(
    "Settings this app doesn't edit, such as interfaces, vPC peers, policies and extra VRF or network options, "
    "are kept and written back unchanged.",
    icon=":material/shield:",
)

tab_folder, tab_upload = st.tabs(["From a folder", "Upload files"])

with tab_folder:
    root = st.text_input(
        "NaC repo, host_vars or fabric folder",
        value=st.session_state.get("import_root", str(Path.home() / "nac-nd")),
        help="For example ~/nac-nd, ~/nac-nd/host_vars or ~/nac-nd/host_vars/nac-fabric1",
    )
    st.session_state.import_root = root
    dirs = find_fabric_dirs(Path(root)) if root else []
    if root and not dirs:
        st.warning("No folder with NaC VXLAN YAML (a top-level `vxlan:` key) was found there.")
    elif dirs:
        home = str(Path.home())
        choice = st.selectbox("Fabric folder", dirs, format_func=lambda d: str(d).replace(home, "~", 1))
        if st.button("Read folder", type="primary", icon=":material/folder_open:"):
            st.session_state.import_result = import_folder(choice)

with tab_upload:
    ups = st.file_uploader(
        "YAML files or a zip",
        type=["yaml", "yml", "zip"],
        accept_multiple_files=True,
        key=key("yaml_upload"),
        help="Select all of the fabric's files at once, or a zip such as the one this app exports.",
    )
    if ups and st.button("Read files", type="primary", icon=":material/upload:"):
        st.session_state.import_result = import_uploads([(u.name, u.getvalue()) for u in ups])

res: ImportResult | None = st.session_state.get("import_result")
if res:
    st.subheader("Result", divider="gray")
    if res.files:
        st.caption(f"Read {len(res.files)} file(s): {', '.join(res.files)}")
    if res.errors:
        st.error("Couldn't import:\n\n" + "\n".join(f"- {e}" for e in res.errors))
    for n in res.notes:
        st.info(n, icon=":material/info:")
    if res.project:
        p = res.project
        cols = st.columns(5)
        cols[0].metric("Fabric", p.fabric.name)
        cols[1].metric("Switches", len(p.switches))
        cols[2].metric("VRFs", len(p.vrfs))
        cols[3].metric("Networks", len(p.networks))
        cols[4].metric("Attach groups", len(p.attach_groups()))
        kept = p.preserved.summary()
        if kept:
            with st.expander(f"Kept unchanged ({len(kept)})", icon=":material/inventory_2:"):
                st.markdown("\n".join(f"- {k}" for k in kept))
        issues = check_project(p)
        errs = [i for i in issues if i.level == "error"]
        if errs:
            with st.expander(f"⛔ {len(errs)} check error(s) to fix after loading"):
                st.markdown("\n".join(f"- **{i.section}**: {i.message}" for i in errs))

        replacing = bool(project().switches or project().vrfs or project().networks)
        label = "Load into the app (replaces the current project)" if replacing else "Load into the app"
        if st.button(label, type="primary", icon=":material/check:"):
            del st.session_state["import_result"]
            set_project(p, f"Imported {p.fabric.name}")
            st.switch_page("views/switches.py")
