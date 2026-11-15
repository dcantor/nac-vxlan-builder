import re

import streamlit as st
from pydantic import ValidationError

from nacbuilder.defaults import group_all_leafs, groups_per_border_set, groups_per_leaf, merge_attachments
from nacbuilder.models import Attachment
from nacbuilder.ui import build_rows, fmt_errors, frame, key, project, records, save, section_issues, show_errors

p = project()

st.title("Attach groups")
st.caption(
    "Named sets of switches that VRFs and networks are deployed to. Ports only apply when a "
    "network uses the group (written to `network_attach_groups`)."
)

if not p.switches:
    st.info("Add switches first.", icon=":material/info:")

with st.form("quick_groups"):
    ports_txt = st.text_input("Access ports for quick groups (optional)", placeholder="Ethernet1/13, Ethernet1/14")
    c1, c2, c3 = st.columns(3)
    add_all = c1.form_submit_button("+ 'all' group", use_container_width=True, help="One group named 'all' with every leaf (no borders)")
    add_each = c2.form_submit_button("+ group per leaf", use_container_width=True, help="One group per leaf, named after the switch")
    add_border = c3.form_submit_button(
        "+ border groups", use_container_width=True, help="border-client, border-internal and border-external, one per border pair"
    )
if add_all or add_each or add_border:
    try:
        ports = [x for x in re.split(r"[,\s]+", ports_txt) if x]
        if add_all:
            new = group_all_leafs(p, ports=ports)
        elif add_each:
            new = groups_per_leaf(p, ports=ports)
        else:
            new = groups_per_border_set(p, ports=ports)
        save(f"Added {len(new)} attachment(s)", attachments=merge_attachments(p.attachments, new))
    except ValidationError as e:
        show_errors(fmt_errors(e))

COLS = {"group": "string", "hostname": "string", "ports": "string"}
names = [s.name for s in p.switches]
rows = [{"group": a.group, "hostname": a.hostname, "ports": ", ".join(a.ports)} for a in p.attachments]

with st.form("attach"):
    df = st.data_editor(
        frame(rows, COLS),
        num_rows="dynamic",
        use_container_width=True,
        key=key("attach"),
        column_config={
            "group": st.column_config.TextColumn("Group", required=True),
            "hostname": st.column_config.SelectboxColumn("Switch", options=sorted(set(names) | {a.hostname for a in p.attachments}), required=True),
            "ports": st.column_config.TextColumn("Ports", help="Comma separated, e.g. Ethernet1/13, port-channel10"),
        },
    )
    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    items, errors = build_rows(records(df), lambda r: Attachment(**r), "Attach")
    if errors:
        show_errors(errors)
    else:
        save(f"Saved {len(items)} attachment(s)", attachments=items)

groups = p.attach_groups()
if groups:
    st.subheader("Summary", divider="gray")
    st.dataframe(
        [{"group": g, "switches": len(r), "members": ", ".join(a.hostname for a in r)} for g, r in groups.items()],
        use_container_width=True,
        hide_index=True,
    )

section_issues("Attach groups")
