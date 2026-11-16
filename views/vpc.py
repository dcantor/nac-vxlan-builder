import streamlit as st
from pydantic import ValidationError

from nacbuilder.defaults import pair_vpc
from nacbuilder.models import SPINE_ROLES
from nacbuilder.tabular import VPC_COLS, vpc_from_row, vpc_to_row
from nacbuilder.ui import TABLE_HELP, build_rows, csv_import, fmt_errors, frame, key, project, records, save, section_issues, show_errors

p = project()

st.title("vPC pairs")
st.caption("Leaf and border pairs that act as one switch for dual-homed hosts → `vxlan.topology.vpc_peers`")

paired = {x for v in p.vpc_peers for x in (v.peer1, v.peer2)}
candidates = [s for s in p.switches if s.role not in SPINE_ROLES]
c1, c2, c3 = st.columns(3)
c1.metric("vPC pairs", len(p.vpc_peers))
c2.metric("Paired switches", len(paired))
c3.metric("Unpaired leafs/borders", len([s for s in candidates if s.name not in paired]))

with st.expander("Pair automatically", expanded=not p.vpc_peers, icon=":material/bolt:"):
    st.caption("Pairs each border set (client, internal, external), then leafs in name order: leaf1 + leaf2, leaf3 + leaf4, …")
    with st.form("pair"):
        fabric_peering = st.toggle("Fabric peering (virtual peer link, no physical peer-link ports)")
        have_models = any(x.model for x in candidates)
        source = st.radio("Peer-link ports", ["From each switch's model", "Same ports on every pair"],
                          index=0 if have_models else 1, horizontal=True,
                          help="From the model: the last two uplink ports (Ethernet1/53-54 on a 54-port leaf).")
        links = st.text_input("Ports (same on every pair)", "Ethernet1/53, Ethernet1/54")
        go = st.form_submit_button("Add pairs")
    if go:
        try:
            ports = [] if fabric_peering else (None if source.startswith("From") else
                                               [x.strip() for x in links.split(",") if x.strip()])
            new = pair_vpc(p, peerlink_ports=ports, fabric_peering=fabric_peering)
            save(f"Added {len(new)} vPC pair(s)" if new else "No unpaired leafs or border sets left", vpc_peers=[*p.vpc_peers, *new])
        except ValidationError as e:
            show_errors(fmt_errors(e))

csv_import("vpc", "vpc_peers", VPC_COLS, vpc_from_row, required=["peer1", "peer2"])

names = sorted({s.name for s in candidates} | paired)
st.caption(TABLE_HELP)
with st.form("vpc"):
    df = st.data_editor(
        frame([vpc_to_row(v) for v in p.vpc_peers], VPC_COLS),
        num_rows="dynamic",
        width="stretch",
        key=key("vpc"),
        column_config={
            "peer1": st.column_config.SelectboxColumn("Peer 1", options=names, required=True),
            "peer2": st.column_config.SelectboxColumn("Peer 2", options=names, required=True),
            "domain_id": st.column_config.NumberColumn("Domain ID", min_value=1, max_value=1000, step=1),
            "fabric_peering": st.column_config.CheckboxColumn("Fabric peering"),
            "peer1_peerlink_interfaces": st.column_config.TextColumn("Peer-link ports on peer 1", help="e.g. Ethernet1/53, Ethernet1/54"),
            "peer2_peerlink_interfaces": st.column_config.TextColumn("Peer-link ports on peer 2"),
        },
    )
    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    pairs, errors = build_rows(records(df), vpc_from_row, "vPC")
    if errors:
        show_errors(errors)
    else:
        save(f"Saved {len(pairs)} vPC pair(s)", vpc_peers=pairs)

section_issues("vPC")
