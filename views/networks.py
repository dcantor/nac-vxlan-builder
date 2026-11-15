import streamlit as st

from nacbuilder.defaults import next_network
from nacbuilder.models import Network
from nacbuilder.ui import build_rows, frame, key, project, records, save, section_issues, show_errors

p = project()

st.title("Networks")
st.caption("Layer-3 networks inside the VRFs: network ID is the L2 VNI → `networks.nac.yaml`")

if not p.vrfs:
    st.info("Add a VRF first.", icon=":material/info:")
if st.button("Add network", icon=":material/add:", help="Appends a network with the next free VNI and VLAN"):
    save(None, networks=[*p.networks, next_network(p)])

COLS = {
    "name": "string",
    "vrf_name": "string",
    "net_id": "Int64",
    "vlan_id": "Int64",
    "vlan_name": "string",
    "gw_ip_address": "string",
    "gw_ipv6_address": "string",
    "network_attach_group": "string",
    "mtu_l3intf": "Int64",
    "int_desc": "string",
    "route_target_both": "bool",
    "l3gw_on_border": "bool",
}
vrf_names = sorted({v.name for v in p.vrfs} | {n.vrf_name for n in p.networks if n.vrf_name})
groups = sorted(set(p.attach_groups()) | {n.network_attach_group for n in p.networks if n.network_attach_group})

with st.form("networks"):
    df = st.data_editor(
        frame([n.to_nac() for n in p.networks], COLS),
        num_rows="dynamic",
        use_container_width=True,
        key=key("networks"),
        column_config={
            "name": st.column_config.TextColumn("Name", required=True, max_chars=64),
            "vrf_name": st.column_config.SelectboxColumn("VRF", options=vrf_names, required=True),
            "net_id": st.column_config.NumberColumn("Net ID (L2 VNI)", min_value=1, max_value=16777214, step=1, required=True),
            "vlan_id": st.column_config.NumberColumn("VLAN", min_value=2, max_value=4094, step=1, required=True),
            "vlan_name": st.column_config.TextColumn("VLAN name", help="Blank = <name>_vlan<id>"),
            "gw_ip_address": st.column_config.TextColumn("Gateway IPv4", help="e.g. 192.168.10.1/24"),
            "gw_ipv6_address": st.column_config.TextColumn("Gateway IPv6"),
            "network_attach_group": st.column_config.SelectboxColumn("Attach group", options=groups),
            "mtu_l3intf": st.column_config.NumberColumn("SVI MTU", min_value=68, max_value=9216, step=1),
            "int_desc": st.column_config.TextColumn("SVI description"),
            "route_target_both": st.column_config.CheckboxColumn("RT both"),
            "l3gw_on_border": st.column_config.CheckboxColumn("L3 GW on border"),
        },
    )
    submitted = st.form_submit_button("Save", type="primary")


def from_row(r: dict) -> Network:
    for flag in ("route_target_both", "l3gw_on_border"):
        if not r.get(flag):
            r.pop(flag, None)  # unchecked = leave unset (ND default false)
    r.setdefault("vlan_name", f"{r.get('name')}_vlan{r.get('vlan_id')}")
    return Network(**r)


if submitted:
    nets, errors = build_rows(records(df), from_row, "Network")
    if errors:
        show_errors(errors)
    else:
        save(f"Saved {len(nets)} network(s)", networks=nets)

section_issues("Networks")
