import streamlit as st

from nacbuilder.defaults import next_vrf
from nacbuilder.tabular import VRF_COLS, vrf_from_row
from nacbuilder.ui import build_rows, csv_import, frame, key, project, records, save, section_issues, show_errors

p = project()

st.title("VRFs")
st.caption("Tenant VRFs: VRF ID is the L3 VNI → `vrfs.nac.yaml`")

if st.button("Add VRF", icon=":material/add:", help="Appends a VRF with the next free VNI and VLAN"):
    save(None, vrfs=[*p.vrfs, next_vrf(p)])

csv_import("vrfs", "vrfs", VRF_COLS, vrf_from_row, required=["name", "vrf_id", "vlan_id"])

groups = sorted(set(p.attach_groups()) | {v.vrf_attach_group for v in p.vrfs if v.vrf_attach_group})

with st.form("vrfs"):
    df = st.data_editor(
        frame([v.to_nac() for v in p.vrfs], VRF_COLS),
        num_rows="dynamic",
        use_container_width=True,
        key=key("vrfs"),
        column_config={
            "name": st.column_config.TextColumn("Name", required=True, max_chars=32),
            "vrf_id": st.column_config.NumberColumn("VRF ID (L3 VNI)", min_value=1, max_value=16777214, step=1, required=True),
            "vlan_id": st.column_config.NumberColumn("VLAN", min_value=2, max_value=4094, step=1, required=True),
            "vrf_attach_group": st.column_config.SelectboxColumn("Attach group", options=groups),
        },
    )
    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    vrfs, errors = build_rows(records(df), vrf_from_row, "VRF")
    if errors:
        show_errors(errors)
    else:
        save(f"Saved {len(vrfs)} VRF(s)", vrfs=vrfs)

section_issues("VRFs")
