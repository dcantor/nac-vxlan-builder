import hashlib

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from nacbuilder.checks import check_project
from nacbuilder.defaults import expand_ports
from nacbuilder.diffing import compare_projects
from nacbuilder.models import ATTACHABLE_ROLES, Project
from nacbuilder.tasks import (
    HostPorts,
    TrunkSpec,
    add_vlan,
    add_vrf,
    extend,
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

if not p.is_vxlan:
    st.info("This fabric uses the Non-VXLAN design: tenant, VRF, VLAN and leaf-pair tasks don't apply. "
            "Decommission is available below.", icon=":material/info:")
    (tab_remove,) = st.tabs(["Decommission"])
else:
    tab_tenant, tab_vrf, tab_vlan, tab_extend, tab_leafs, tab_remove = st.tabs(
        ["New tenant", "Add VRF", "Add VLAN", "Extend to switches", "Onboard a leaf pair", "Decommission"])

attachable = [s.name for s in p.switches if s.role in ATTACHABLE_ROLES]
leafs = [s.name for s in p.switches if s.role == "leaf"]
trunk_switches = sorted({i.switch for i in p.interfaces if i.mode == "trunk"})

# --- add VRF ------------------------------------------------------------------------
if p.is_vxlan:
    with tab_vrf:
        st.caption("A VRF on its own, ready for VLANs. It can use an existing attach group or a new one with the switches you pick.")
        groups = sorted(p.attach_groups())
        with st.form("add_vrf"):
            c1, c2, c3 = st.columns([2, 1, 1])
            name = c1.text_input("VRF name", placeholder="DEV")
            vid = c2.number_input("VRF ID (0 = next free)", 0, 16777214, 0, key="addvrf_id")
            vvlan = c3.number_input("VLAN (0 = next free)", 0, 4094, 0, key="addvrf_vlan")
            where = st.radio("Deploy to", ["New group with these switches", "Existing attach group"], horizontal=True)
            c1, c2 = st.columns(2)
            sws = c1.multiselect("Switches (new group)", attachable, default=leafs)
            grp = c2.selectbox("Existing group", groups or ["(none)"])
            with_lite = st.toggle("Hand the VRF off to external routers (VRF-lite)", key="addvrf_lite",
                                  disabled=not border_switches(p, "external"))
            c1, c2, c3, c4 = st.columns(4)
            lite_sw = c1.multiselect("Borders", [s.name for s in p.switches if s.role in BORDER_ROLES],
                                     default=border_switches(p, "external"), key="addvrf_lsw")
            lite_up = c2.text_input("Uplink port(s)", "Ethernet1/48", key="addvrf_up")
            lite_pool = c3.text_input("Link pool", "10.254.0.0/24", key="addvrf_pool")
            lite_as = c4.number_input("Neighbor ASN", 1, 4294967295, 65500, key="addvrf_as")
            go = st.form_submit_button("Preview", type="primary")
        if go:
            try:
                if not name.strip():
                    raise ValueError("enter a VRF name")
                lite = VrfLiteSpec(lite_sw, [x.strip() for x in lite_up.split(",") if x.strip()], lite_pool, 30,
                                   int(lite_as)) if with_lite else None
                existing = where.startswith("Existing")
                if existing and grp not in groups:
                    raise ValueError("there are no attach groups yet; deploy to a new group instead")
                q = add_vrf(p, name.strip(), attach_group=grp if existing else None, switches=None if existing else sws,
                            vrf_id=int(vid) or None, vlan_id=int(vvlan) or None, vrf_lite=lite)
                stage(f"Add VRF {name.strip()}", q)
            except (ValidationError, ValueError) as e:
                fail(e)

# --- add VLAN ---------------------------------------------------------------------------
if p.is_vxlan:
    with tab_vlan:
        if not p.vrfs:
            st.info("Add a VRF first.", icon=":material/info:")
        else:
            st.caption("New VLANs (networks) in an existing VRF. VLAN and VNI are picked automatically when blank. "
                       "Optionally allow them on host trunks too; the VLANs and their VRF are then deployed to those switches.")
            with st.form("add_vlan"):
                c1, c2 = st.columns(2)
                vrf_pick = c1.selectbox("VRF", [v.name for v in p.vrfs])
                grp_opts = ["(same as the VRF's other VLANs)", *sorted(p.attach_groups("network") | p.attach_groups())]
                grp_pick = c2.selectbox("Attach group", list(dict.fromkeys(grp_opts)))
                vlan_df = st.data_editor(
                    pd.DataFrame({"name": pd.Series(dtype="string"), "gw_ip_address": pd.Series(dtype="string"),
                                  "vlan_id": pd.Series(dtype="Int64")}),
                    num_rows="dynamic", use_container_width=True, key=key("vlan_rows"),
                    column_config={
                        "name": st.column_config.TextColumn("Network name", required=True),
                        "gw_ip_address": st.column_config.TextColumn("Gateway IPv4", help="e.g. 10.20.9.1/24; blank = Layer-2 style, no SVI IP"),
                        "vlan_id": st.column_config.NumberColumn("VLAN", min_value=2, max_value=4094, step=1),
                    },
                )
                c1, c2, c3 = st.columns([2, 1, 1])
                trunk_sws = c1.multiselect("Also allow on trunks of", trunk_switches,
                                           help="Switches with trunk ports. Their trunks get the new VLAN IDs added.")
                peers = c2.checkbox("Include vPC peers", value=True)
                pc_only = c3.checkbox("Port-channels only", value=False)
                go = st.form_submit_button("Preview", type="primary")
            if go:
                try:
                    specs = [NetworkSpec(name=r["name"], gw_ip_address=r.get("gw_ip_address"), vlan_id=r.get("vlan_id"))
                             for r in records(vlan_df) if r.get("name")]
                    trunks = TrunkSpec(trunk_sws, peers, pc_only) if trunk_sws else None
                    q = add_vlan(p, vrf_pick, specs, attach_group=None if grp_pick.startswith("(") else grp_pick, trunks=trunks)
                    stage(f"Add {len(specs)} VLAN(s) to {vrf_pick}", q)
                except (ValidationError, ValueError) as e:
                    fail(e)

# --- extend to switches ---------------------------------------------------------------------
if p.is_vxlan:
    with tab_extend:
        st.caption("Deploy existing VLANs or VRFs to more switches. A VLAN's VRF follows it. If a group is shared, "
                   "the VLAN or VRF gets its own copy so nothing else moves.")
        with st.form("extend"):
            c1, c2 = st.columns(2)
            nets = c1.multiselect("VLANs (networks)", [f"{n.name}" for n in p.networks],
                                  format_func=lambda n: f"{n} (VLAN {next(x.vlan_id for x in p.networks if x.name == n)})")
            vrfs_x = c2.multiselect("VRFs", [v.name for v in p.vrfs])
            c1, c2 = st.columns([3, 1])
            to = c1.multiselect("To switches", attachable)
            peers_x = c2.checkbox("Include vPC peers", value=True, key="extend_peers")
            go = st.form_submit_button("Preview", type="primary")
        if go:
            try:
                q = extend(p, to, networks=nets, vrfs=vrfs_x, include_vpc_peers=peers_x)
                stage(f"Extend {', '.join(nets + vrfs_x)} to {', '.join(to)}", q)
            except (ValidationError, ValueError) as e:
                fail(e)

# --- new tenant -------------------------------------------------------------------
if p.is_vxlan:
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
if p.is_vxlan:
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
        c1, c2 = st.columns([3, 1])
        nets = c1.multiselect("VLANs (networks)", [n.name for n in p.networks],
                              format_func=lambda n: f"{n} (VLAN {next(x.vlan_id for x in p.networks if x.name == n)})")
        strip = c2.checkbox("Remove the VLANs from trunks", value=True)
        go = st.form_submit_button("Preview", type="primary")
    if go:
        try:
            if not sws and not vrfs and not nets:
                raise ValueError("pick at least one switch, VRF or VLAN")
            q = decommission(p, switches=sws, vrfs=vrfs, include_vpc_peer=peer, networks=nets, strip_trunks=strip)
            stage("Decommission " + ", ".join(sws + vrfs + nets), q)
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
    before = {(i.section, i.message) for i in check_project(p)}
    new_issues = [i for i in check_project(q) if (i.section, i.message) not in before]
    new_errors = [i for i in new_issues if i.level == "error"]
    new_warnings = [i for i in new_issues if i.level == "warning"]
    if new_errors:
        st.error("This change introduces errors:\n\n" + "\n".join(f"- **{i.section}**: {i.message}" for i in new_errors))
    if new_warnings:
        st.warning("New warnings:\n\n" + "\n".join(f"- **{i.section}**: {i.message}" for i in new_warnings))
    if not new_issues:
        st.success("No new errors or warnings.", icon="✅")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Apply", type="primary", disabled=pv["base"] != fingerprint(p), use_container_width=True):
        del st.session_state["task_preview"]
        set_project(q, pv["label"])
        st.rerun()
    if c2.button("Discard", use_container_width=True):
        del st.session_state["task_preview"]
        st.rerun()
