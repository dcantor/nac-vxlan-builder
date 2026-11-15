from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from nacbuilder import standards as std
from nacbuilder.checks import check_project
from nacbuilder.clone import CloneSpec, clone_fabric, suggest
from nacbuilder.diffing import change_summary, file_diffs
from nacbuilder.generate import apply_write, plan_write, render_all, zip_bytes
from nacbuilder.paths import fabric_export_dir
from nacbuilder.settings import (
    COLLECTION_NAME,
    Settings,
    collection_version,
    find_collection_rules,
    install_cisco_rules,
    is_windows,
    load_settings,
    resolve_rules,
    rules_supported,
    save_settings,
)
from nacbuilder.validate import nac_validate
from nacbuilder.ui import project, set_project

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

st.subheader("Validation", divider="gray")
cfg = load_settings()
with st.expander("Validation settings", icon=":material/tune:"):
    schema_txt = st.text_input(
        "Full schema file (blank = bundled simplified schema)", cfg.schema_path,
        help="e.g. the schema.yaml your NaC repo points DC_VXLAN_SCHEMA at",
    )
    use_rules, rules_txt = cfg.use_rules, cfg.rules_path
    if rules_supported():
        detected = find_collection_rules()
        st.markdown("**Cisco's semantic rules**")
        if detected:
            st.caption(f"`{COLLECTION_NAME}` {collection_version(detected) or ''} is installed: `{detected}`. "
                       "Its rules are Python code that runs on this Mac when you validate.")
        else:
            st.caption(f"`{COLLECTION_NAME}` isn't installed. **Install** adds `ansible-core` to this app's Python "
                       "environment and the collection to `~/.ansible/collections` (downloads from PyPI and "
                       "Ansible Galaxy, about 100 MB). It can take a few minutes.")
            if st.button("Install Cisco's rules", icon=":material/download:", type="primary"):
                with st.spinner("Installing ansible-core and cisco.nac_dc_vxlan…"):
                    result = install_cisco_rules()
                st.session_state.rules_install = result
                st.rerun()
        if (res := st.session_state.get("rules_install")) is not None:
            (st.success if res.ok else st.error)("Installed." if res.ok else "Install failed:", icon="✅" if res.ok else "⛔")
            with st.expander("Install log", expanded=not res.ok):
                st.code(res.log, language="text")
        use_rules = st.checkbox("Run Cisco's semantic rules when validating", cfg.use_rules)
        rules_txt = st.text_input(
            "Rules folder (blank = the installed collection)", cfg.rules_path,
            placeholder=str(detected) if detected else "…/ansible_collections/cisco/nac_dc_vxlan/roles/validate/files/rules",
        )
    else:
        where = "Windows" if is_windows() else "this operating system"
        st.caption(f"Cisco's semantic rules come with an Ansible collection, and Ansible doesn't run on {where}, so "
                   "they're offered only when the app runs on macOS. Validation here uses the schema.")
    if st.button("Save settings"):
        problems = []
        if schema_txt and not Path(schema_txt).expanduser().is_file():
            problems.append(f"{schema_txt} isn't a file.")
        if rules_txt and not Path(rules_txt).expanduser().is_dir():
            problems.append(f"{rules_txt} isn't a folder.")
        if problems:
            st.error(" ".join(problems))
        else:
            save_settings(Settings(schema_path=schema_txt, rules_path=rules_txt, use_rules=use_rules))
            st.toast("Validation settings saved", icon="✅")
            st.rerun()

rules = resolve_rules(cfg, fabric_type=std.get(p.standard).fabric_type)
schema = Path(cfg.schema_path).expanduser() if cfg.schema_path else None
what = f"{'full schema' if schema else 'bundled schema'}" + (f" + {len(rules)} rule set(s): {', '.join(r.name for r in rules)}" if rules else "")
c1, c2 = st.columns([1, 3])
if c1.button("Run nac-validate", icon=":material/rule:", help=f"Checks the generated files with nac-validate ({what})"):
    with st.spinner(f"Validating ({what})…"):
        try:
            st.session_state.last_validation = nac_validate(p, schema=schema, rules=rules)
        except (OSError, FileNotFoundError) as e:
            st.session_state.last_validation = None
            c2.error(f"Couldn't run nac-validate: {e}")
c2.caption(f"Uses the {what}.")
if res := st.session_state.get("last_validation"):
    mode = "" if res.strict else " in non-strict mode (imported settings outside the bundled schema are allowed)"
    ran = f" and {len(res.rules)} rule set(s)" if res.rules else ""
    if res.ok:
        st.success(f"nac-validate passed: {'full' if res.schema != 'bundled' else 'bundled'} schema{ran}{mode}.", icon="✅")
    else:
        st.error("nac-validate reported problems:", icon="⛔")
    if res.output:
        st.code(res.output, language="text")

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

st.markdown("**Write to a folder**")
pv = p.preserved
imported_from_folder = pv.source not in (None, "upload")
default_dest = pv.source if imported_from_folder else str(fabric_export_dir(p.fabric.name))
dest_txt = st.text_input(
    "Fabric folder",
    default_dest,
    key=f"dest_{p.fabric.name}",
    help="Defaults to export/<fabric>/ in the app folder, or to the folder the fabric was imported from. "
    "To write straight into a NaC repo, use <repo>/host_vars/<fabric>.",
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
    st.markdown("**Changes**")
    summary = change_summary(p, dest)
    diffs = file_diffs(p, dest, remove_stale=remove)
    changed = [d for d in diffs if d.status != "unchanged"]
    if summary is not None:
        if summary.empty:
            st.caption("No switch, vPC, interface, VRF, network, attach group or VRF-lite changes compared with the folder.")
        else:
            c1, c2, c3 = st.columns(3)
            for col, label, items, icon in (
                (c1, "Added", summary.added, "🟢"),
                (c2, "Removed", summary.removed, "🔴"),
                (c3, "Changed", summary.changed, "🟡"),
            ):
                col.markdown(f"{icon} **{label} ({len(items)})**")
                if items:
                    col.markdown("\n".join(f"- {i}" for i in items[:40]) + (f"\n- … {len(items) - 40} more" if len(items) > 40 else ""))
    if not changed:
        st.success("The folder already matches the generated files.", icon="✅")
    for d in diffs:
        if d.status == "unchanged":
            continue
        badge = {"new": "new file", "removed": "will be deleted", "changed": "changed"}[d.status]
        with st.expander(f"`{d.name}`: {badge} (+{d.added} −{d.removed})"):
            st.code(d.diff or "(empty)", language="diff")
    if [d.name for d in diffs if d.status == "unchanged"]:
        st.caption("Unchanged: " + ", ".join(f"`{d.name}`" for d in diffs if d.status == "unchanged"))

    if st.button("Write files", disabled=not confirm or not changed, icon=":material/save:"):
        written, removed = apply_write(p, dest, remove_stale=remove)
        msg = f"Wrote {len(written)} file(s) to {dest}"
        if removed:
            msg += f" and deleted {', '.join(removed)}"
        st.success(msg + ".")

st.markdown("**Clone fabric**")
with st.expander("Make a copy of this fabric under a new name", icon=":material/content_copy:"):
    st.caption(
        "Builds a new fabric from this one (for example `dc1` → `dc2`), renaming every switch everywhere it's "
        "used: vPC pairs, interfaces, attach groups, VRF-lite and kept settings. The clone opens in place of "
        "this fabric; Undo or History brings the original back."
    )
    sug = suggest(p)
    with st.form(f"clone_{p.fabric.name}"):
        c1, c2, c3 = st.columns(3)
        c_name = c1.text_input("New fabric name", sug.name)
        c_old = c2.text_input("Replace switch-name prefix", sug.old_prefix, help="Blank = keep the switch names.")
        c_new = c3.text_input("with", sug.new_prefix)
        c1, c2, c3 = st.columns(3)
        ips = sorted(s.management.management_ipv4_address for s in p.switches
                     if s.management and s.management.management_ipv4_address)
        c_ip = c1.text_input(
            "New first management IP", "", placeholder=f"blank = keep (now {ips[0]})" if ips else "no management IPs",
            help="The lowest management IP moves here; every other management IP and gateway moves by the same amount.",
            disabled=not ips,
        )
        c_asn = c2.text_input("BGP ASN", p.ibgp.bgp_asn)
        c_serials = c3.checkbox("Clear serial numbers", True, help="Serials belong to physical switches.")
        c_write = st.checkbox("Also write the clone's YAML to export/<new name>/", True)
        go = st.form_submit_button("Clone fabric", type="primary", icon=":material/content_copy:")
    if go:
        spec = CloneSpec(name=c_name.strip(), old_prefix=c_old.strip(), new_prefix=c_new.strip(),
                         clear_serials=c_serials, first_mgmt_ip=c_ip.strip() or None,
                         bgp_asn=None if c_asn.strip() == p.ibgp.bgp_asn else c_asn.strip())
        try:
            clone = clone_fabric(p, spec)
        except (ValueError, ValidationError) as e:
            st.error(f"Not cloned: {e}")
        else:
            msg = f"Cloned {p.fabric.name} to {clone.fabric.name}"
            if c_write:
                out = fabric_export_dir(clone.fabric.name)
                if plan_write(clone, out).replace:  # never overwrite silently; write from this page instead
                    msg += f". export/{clone.fabric.name}/ already has files, so nothing was written: review and write below"
                else:
                    written, _ = apply_write(clone, out, remove_stale=False)
                    msg += f" and wrote {len(written)} file(s) to export/{clone.fabric.name}/"
            set_project(clone, msg)
            st.rerun()
