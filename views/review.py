from pathlib import Path

import streamlit as st

from nacbuilder.checks import check_project
from nacbuilder.generate import host_vars_dir, render_all, write_host_vars, zip_bytes
from nacbuilder.validate import nac_validate
from nacbuilder.ui import project

p = project()

st.title("Review & export")

issues = check_project(p)
errors = [i for i in issues if i.level == "error"]
warnings = [i for i in issues if i.level == "warning"]

st.subheader("Checks", divider="gray")
if not issues:
    st.success("No problems found.", icon="✅")
for i in errors:
    st.error(f"**{i.section}**: {i.message}", icon="⛔")
for i in warnings:
    st.warning(f"**{i.section}**: {i.message}", icon="⚠️")

c1, c2 = st.columns([1, 3])
if c1.button("Run nac-validate", icon=":material/rule:", help="Validates the files against schema/schema.yaml"):
    with st.spinner("Validating…"):
        res = nac_validate(p)
    st.session_state.last_validation = res
if res := st.session_state.get("last_validation"):
    if res.ok:
        c2.success("nac-validate passed against the schema.", icon="✅")
    else:
        c2.error("nac-validate reported problems:", icon="⛔")
        st.code(res.output or "(no output)", language="text")

st.subheader("Files", divider="gray")
files = render_all(p)
tabs = st.tabs(list(files))
for tab, (name, text) in zip(tabs, files.items()):
    with tab:
        st.code(text, language="yaml", line_numbers=True)

st.subheader("Export", divider="gray")
if errors:
    st.caption(f"⛔ {len(errors)} error(s) above. You can still export, but Nexus Dashboard will likely reject the result.")

st.download_button(
    "Download zip",
    zip_bytes(p),
    file_name=f"{p.fabric.name}-host_vars.zip",
    mime="application/zip",
    icon=":material/download:",
    type="primary",
)

with st.form("write"):
    st.markdown("**Write into a NaC repo**, e.g. a clone of `ansible-dc-vxlan-example`")
    root = st.text_input("Repo folder", str(Path.home() / "nac-nd"))
    st.caption(f"Files go to `<repo>/host_vars/{p.fabric.name}/`. Existing files with the same names are replaced.")
    overwrite = st.checkbox("Replace existing files")
    go = st.form_submit_button("Write files")
if go:
    repo = Path(root).expanduser()
    dest = host_vars_dir(p, repo)
    existing = [n for n in files if (dest / n).exists()]
    if not repo.is_dir():
        st.error(f"{repo} isn't a folder.")
    elif existing and not overwrite:
        st.warning(f"{', '.join(existing)} already exist in {dest}. Tick **Replace existing files** to overwrite them.")
    else:
        written = write_host_vars(p, repo)
        st.success(f"Wrote {len(written)} file(s) to {dest}")
