import hashlib

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from nacbuilder.checks import check_project
from nacbuilder.defaults import expand_ports
from nacbuilder.diffing import compare_projects
from nacbuilder.models import Project
from nacbuilder.tasks import (
    HostPorts,
    NetworkSpec,
    VrfLiteSpec,
    border_switches,
    decommission,
    new_tenant,
    next_leaf_names,
    next_mgmt_ips,
    onboard_leaf_pair,
)
from nacbuilder.ui import fmt_errors, key, project, records, set_project, show_errors

BORDER_ROLES = ("border", "border_spine", "border_gateway", "border_gateway_spine")

p = project()


def fingerprint(x: Project) -> str:
    return hashlib.sha1(x.model_dump_json().encode()).hexdigest()


def stage(label: str, q: Project) -> None:
    st.session_state.task_preview = {"label": label, "project": q, "base": fingerprint(p)}
    st.rerun()


def fail(e: Exception) -> None:
    show_errors(fmt_errors(e) if isinstance(e, ValidationError) else [str(e)], "Can't preview this change:")


st.title("Day-2 tasks")
st.caption("Common changes that touch several pages at once. Each shows a preview first; nothing changes until you apply it.")

tab_tenant, tab_leafs, tab_remove = st.tabs(["New tenant", "Onboard a leaf pair", "Decommission"])

# --- new tenant -------------------------------------------------------------------
with tab_tenant:
    groups = sorted(p.attach_groups())
    borders = [s.name for s in p.switches if s.role in BORDER_ROLES]
    with st.form("tenant"):
        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
        vrf_name = c1.text_input("VRF name", placeholder="PROD")
        group = c2.text_input("Attach group", "all" if "all" in groups or not groups else groups[0],
                              help="Used by the VRF and its networks. A new group is created with every leaf if it doesn't exist.")
        vrf_id = c3.number_input("VRF ID (0 = next free)", 0, 16777214, 0)
        vrf_vlan = c4.number_input("VLAN (0 = next free)", 0, 4094, 0)
        st.markdown("**Networks** (VLAN and network ID are allocated automatically when blank)")
        nets_df = st.data_editor(
            pd.DataFrame({"name": pd.Series(dtype="string"), "gw_ip_address": pd.Series(dtype="string"),
                          "vlan_id": pd.Series(dtype="Int64")}),
            num_rows="dynamic", use_container_width=True, key=key("tenant_nets"),
            column_config={
                "name": st.column_config.TextColumn("Network name", required=True),
                "gw_ip_address": st.column_config.TextColumn("Gateway IPv4", help="e.g. 10.20.1.1/24"),
                "vlan_id": st.column_config.NumberColumn("VLAN", min_value=2, max_value=4094, step=1),
            },
        )
        with_lite = st.toggle("Hand the VRF off to external routers (VRF-lite)", value=False, disabled=not borders)
        c1, c2, c3, c4 = st.columns(4)
        lite_sw = c1.multiselect("Borders", borders, default=border_switches(p, "external"))
        lite_up = c2.text_input("Uplink port(s)", "Ethernet1/48")
        lite_pool = c3.text_input("Link pool", "10.254.0.0/24")
        lite_as = c4.number_input("Neighbor ASN", 1, 4294967295, 65500)
        lite_prefix = st.radio("Link size", [30, 31], horizontal=True, format_func=lambda n: f"/{n}")
        go = st.form_submit_button("Preview", type="primary")
    if go:
        try:
            specs = [NetworkSpec(name=r["name"], gw_ip_address=r.get("gw_ip_address"), vlan_id=r.get("vlan_id"))
                     for r in records(nets_df) if r.get("name")]
            if not vrf_name.strip():
                raise ValueError("enter a VRF name")
            lite = VrfLiteSpec(lite_sw, [x.strip() for x in lite_up.split(",") if x.strip()], lite_pool,
                               int(lite_prefix), int(lite_as)) if with_lite else None
            q = new_tenant(p, vrf_name.strip(), specs, attach_group=group.strip(), vrf_id=int(vrf_id) or None,
                           vrf_vlan=int(vrf_vlan) or None, vrf_lite=lite)
            stage(f"New tenant {vrf_name.strip()} with {len(specs)} network(s)", q)
        except (ValidationError, ValueError) as e:
            fail(e)

# --- onboard a leaf pair ------------------------------------------------------------
with tab_leafs:
    n1, n2 = next_leaf_names(p)
    ips, mask, gw = next_mgmt_ips(p)
    ips = ips or ["", ""]
    with st.form("leafs"):
        c1, c2 = st.columns(2)
        name1 = c1.text_input("Leaf 1", n1)
        name2 = c2.text_input("Leaf 2", n2)
        serial1 = c1.text_input("Serial 1")
        serial2 = c2.text_input("Serial 2")
        ip1 = c1.text_input("Mgmt IP 1", ips[0])
        ip2 = c2.text_input("Mgmt IP 2", ips[1])
        c1, c2 = st.columns(2)
        mgmt_mask = c1.number_input("Mgmt mask", 8, 30, mask or 24)
        mgmt_gw = c2.text_input("Mgmt gateway", gw or "")
        c1, c2 = st.columns(2)
        fabric_peering = c1.toggle("Fabric peering (no physical peer link)")
        peerlink = c2.text_input("Peer-link ports", "Ethernet1/53, Ethernet1/54")
        st.markdown("**Host ports**: one vPC port-channel per port, same port on both leafs")
        c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
        host = c1.text_input("Ports", placeholder="Ethernet1/1-24")
        mode = c2.selectbox("Mode", ["trunk", "access"])
        access_vlan = c3.number_input("Access VLAN", 1, 4094, 1)
        trunk = c4.text_input("Trunk VLANs", placeholder="2300-2399")
        join = st.multiselect("Add to attach groups", sorted(p.attach_groups()),
                              default=["all"] if "all" in p.attach_groups() else [])
        go = st.form_submit_button("Preview", type="primary")
    if go:
        try:
            hp = HostPorts(host, mode, int(access_vlan), trunk or None) if host.strip() else None
            links = [] if fabric_peering else expand_ports(peerlink)
            q = onboard_leaf_pair(p, (name1.strip(), name2.strip()), (serial1.strip(), serial2.strip()),
                                  (ip1.strip(), ip2.strip()), int(mgmt_mask), mgmt_gw.strip() or None, links,
                                  fabric_peering, hp, join)
            stage(f"Onboard {name1.strip()} + {name2.strip()}", q)
        except (ValidationError, ValueError) as e:
            fail(e)

# --- decommission ----------------------------------------------------------------------
with tab_remove:
    with st.form("remove"):
        sws = st.multiselect("Switches", [s.name for s in p.switches])
        peer = st.checkbox("Also remove each switch's vPC peer", value=True,
                           help="A vPC pair is decommissioned together. Untick to keep the peer; its vPC port-channels then lose their vPC ID.")
        vrfs = st.multiselect("VRFs (with their networks and VRF-lite)", [v.name for v in p.vrfs])
        go = st.form_submit_button("Preview", type="primary")
    if go:
        try:
            if not sws and not vrfs:
                raise ValueError("pick at least one switch or VRF")
            q = decommission(p, switches=sws, vrfs=vrfs, include_vpc_peer=peer)
            stage("Decommission " + ", ".join(sws + vrfs), q)
        except (ValidationError, ValueError) as e:
            fail(e)

# --- preview -----------------------------------------------------------------------------
pv = st.session_state.get("task_preview")
if pv:
    st.subheader(f"Preview: {pv['label']}", divider="gray")
    if pv["base"] != fingerprint(p):
        st.warning("The project changed since this preview was made. Discard it and preview again.", icon="⚠️")
    q = pv["project"]
    diff = compare_projects(p, q)
    c1, c2, c3 = st.columns(3)
    for col, title, items, icon in ((c1, "Added", diff.added, "🟢"), (c2, "Removed", diff.removed, "🔴"),
                                   (c3, "Changed", diff.changed, "🟡")):
        col.markdown(f"{icon} **{title} ({len(items)})**")
        if items:
            col.markdown("\n".join(f"- {i}" for i in items[:50]) + (f"\n- … {len(items) - 50} more" if len(items) > 50 else ""))
    before = {(i.section, i.message) for i in check_project(p) if i.level == "error"}
    new_errors = [i for i in check_project(q) if i.level == "error" and (i.section, i.message) not in before]
    if new_errors:
        st.error("This change introduces errors:\n\n" + "\n".join(f"- **{i.section}**: {i.message}" for i in new_errors))
    else:
        st.success("No new check errors.", icon="✅")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Apply", type="primary", disabled=pv["base"] != fingerprint(p), use_container_width=True):
        del st.session_state["task_preview"]
        set_project(q, pv["label"])
        st.rerun()
    if c2.button("Discard", use_container_width=True):
        del st.session_state["task_preview"]
        st.rerun()
