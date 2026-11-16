import re

import streamlit as st
from pydantic import ValidationError

from nacbuilder.defaults import group_all_leafs, groups_per_border_set, groups_per_leaf, groups_per_leaf_role, merge_attachments
from nacbuilder.models import USED_FOR, Attachment
from nacbuilder.ui import TABLE_HELP, build_rows, fmt_errors, frame, key, project, records, save, section_issues, show_errors

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
    c1, c2, c3, c4 = st.columns(4)
    add_all = c1.form_submit_button("+ 'all' group", width="stretch", help="One group named 'all' with every leaf (no borders)")
    add_each = c2.form_submit_button("+ group per leaf", width="stretch", help="One group per leaf, named after the switch")
    add_border = c3.form_submit_button(
        "+ border groups", width="stretch", help="border-client, border-internal and border-external, one per border pair"
    )
    add_lr = c4.form_submit_button(
        "+ group per leaf role", width="stretch", disabled=not p.leaf_roles,
        help="leaf-compute, leaf-storage, ...: one group per leaf role (define leaf roles on the Switches page)"
    )
if add_all or add_each or add_border or add_lr:
    try:
        ports = [x for x in re.split(r"[,\s]+", ports_txt) if x]
        if add_all:
            new = group_all_leafs(p, ports=ports)
        elif add_each:
            new = groups_per_leaf(p, ports=ports)
        elif add_lr:
            new = groups_per_leaf_role(p, ports=ports)
        else:
            new = groups_per_border_set(p, ports=ports)
        save(f"Added {len(new)} attachment(s)", attachments=merge_attachments(p.attachments, new))
    except ValidationError as e:
        show_errors(fmt_errors(e))

names = [s.name for s in p.switches]
orphans = [a for a in p.attachments if a.hostname not in names]
if orphans:
    hosts = sorted({a.hostname for a in orphans})
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.warning(f"{len(orphans)} row(s) point at switches that no longer exist: {', '.join(hosts)}.", icon="⚠️")
    if c2.button("Remove those rows", width="stretch"):
        save(f"Removed {len(orphans)} row(s)", attachments=[a for a in p.attachments if a.hostname in names])

COLS = {"group": "string", "hostname": "string", "used_for": "string", "ports": "string"}
rows = [{"group": a.group, "hostname": a.hostname, "used_for": a.used_for, "ports": ", ".join(a.ports)} for a in p.attachments]
st.caption(TABLE_HELP)

with st.form("attach"):
    df = st.data_editor(
        frame(rows, COLS),
        num_rows="dynamic",
        width="stretch",
        key=key("attach"),
        column_config={
            "group": st.column_config.TextColumn("Group", required=True),
            "hostname": st.column_config.SelectboxColumn("Switch", options=sorted(set(names) | {a.hostname for a in p.attachments}), required=True),
            "used_for": st.column_config.SelectboxColumn(
                "Used for", options=list(USED_FOR), default="both", required=True,
                help="both = VRF and network attach groups; vrf / network = only that list",
            ),
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
        [
            {
                "group": g,
                "VRF members": ", ".join(a.hostname for a in r if a.applies_to("vrf")),
                "network members": ", ".join(a.hostname for a in r if a.applies_to("network")),
            }
            for g, r in groups.items()
        ],
        width="stretch",
        hide_index=True,
    )

section_issues("Attach groups")
