from pathlib import Path

import streamlit as st

from nacbuilder.checks import check_project
from nacbuilder.generate import apply_write, plan_write, render_all, zip_bytes
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
    mode = "" if res.strict else " (non-strict: imported settings outside the bundled schema are allowed)"
    if res.ok:
        c2.success(f"nac-validate passed against the schema{mode}.", icon="✅")
    else:
        c2.error("nac-validate reported problems:", icon="⛔")
        st.code(res.output or "(no output)", language="text")

st.subheader("Files", divider="gray")
if kept := p.preserved.summary():
    with st.expander(f"Imported settings kept unchanged ({len(kept)})", icon=":material/inventory_2:"):
        st.markdown("\n".join(f"- {k}" for k in kept))
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

st.markdown("**Write into a NaC repo**")
pv = p.preserved
imported_from_folder = pv.source not in (None, "upload")
default_dest = pv.source if imported_from_folder else str(Path.home() / "nac-nd" / "host_vars" / p.fabric.name)
dest_txt = st.text_input(
    "Fabric folder (`<repo>/host_vars/<fabric>`)",
    default_dest,
    key=f"dest_{p.fabric.name}",
    help="Defaults to the folder the fabric was imported from.",
)
dest = Path(dest_txt).expanduser()
if not dest.parent.is_dir():
    st.error(f"{dest.parent} doesn't exist.")
else:
    plan = plan_write(p, dest)
    lines = []
    if plan.new:
        lines.append(f"- Create: {', '.join(f'`{n}`' for n in plan.new)}")
    if plan.replace:
        lines.append(f"- Replace: {', '.join(f'`{n}`' for n in plan.replace)}")
    st.markdown("\n".join(lines))
    confirm = True
    if plan.replace:
        confirm = st.checkbox(f"Replace {len(plan.replace)} existing file(s)")
    remove = False
    if plan.stale:
        st.warning(
            f"{', '.join(f'`{n}`' for n in plan.stale)} hold data that's now in the generated files. NaC merges every "
            "file in the folder, so if they stay, switches, VRFs or networks you deleted here come back, and "
            "the rest are duplicated.",
            icon="⚠️",
        )
        remove = st.checkbox(f"Delete {len(plan.stale)} superseded file(s)", value=False)
    if plan.unrelated:
        st.info(
            f"Other NaC files in this folder are left alone: {', '.join(f'`{n}`' for n in plan.unrelated)}. "
            "Make sure they don't define the same switches, VRFs or networks.",
            icon=":material/info:",
        )
    if st.button("Write files", disabled=not confirm, icon=":material/save:"):
        written, removed = apply_write(p, dest, remove_stale=remove)
        msg = f"Wrote {len(written)} file(s) to {dest}"
        if removed:
            msg += f" and deleted {', '.join(removed)}"
        st.success(msg + ".")
