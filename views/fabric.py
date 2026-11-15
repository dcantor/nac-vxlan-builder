import streamlit as st
from pydantic import ValidationError

from nacbuilder import standards as std
from nacbuilder.models import Fabric, GlobalIbgp, ManagementServer, SyslogServer
from nacbuilder.tasks import clear_fabric, clear_summary
from nacbuilder.ui import LOCKED, build_rows, fmt_errors, frame, key, project, records, section_issues, set_project, show_errors

p = project()
g = p.ibgp

st.title("Fabric")
st.caption("Fabric name, design standard and global settings (Nexus Dashboard 4.2) → `global.nac.yaml`")

# The standard is picked outside the form so the fields below follow it right away; it's saved with Save.
keys = list(std.STANDARDS)
picked = st.radio(
    "Design standard",
    keys,
    index=keys.index(p.standard),
    format_func=lambda k: std.STANDARDS[k].label,
    horizontal=True,
    key=f"standard_pick_{p.standard}",
    help="Decides the NaC fabric type, which rules the checks enforce and which pages apply.",
)
S = std.get(picked)
st.info(f"**{S.label}:** {S.summary}", icon=":material/verified:")
if picked != p.standard:
    lost = []
    if not S.vxlan:
        lost = [f"{n} {w}" for n, w in ((len(p.vrfs), "VRF(s)"), (len(p.networks), "network(s)"),
                                       (len(p.vrf_lites), "VRF-lite profile(s)")) if n]
    st.warning(
        f"Not saved yet: switching from {std.get(p.standard).label} to {S.label}."
        + (f" A {S.label} doesn't write VRFs, networks or VRF-lite; this fabric has {', '.join(lost)}." if lost else "")
        + " The underlay, VRF, network and VRF-lite pages are hidden for a Non-VXLAN design."
        * (not S.vxlan),
        icon=":material/swap_horiz:",
    )

locks = std.lock_mismatches(p) if picked == p.standard else []
if locks:
    st.error("This fabric doesn't follow values its design standard locks:\n\n"
             + "\n".join(f"- {label}: {have or 'none'} (locked to {want or 'none'})" for _, label, have, want in locks),
             icon=":material/lock:")
    if st.button("Apply locked values", icon=":material/lock:", type="primary"):
        set_project(std.apply_locks(p), f"Applied {len(locks)} locked value(s) from {S.label}")
        st.rerun()
elif S.locked:
    st.caption(":material/lock: Locked by the standard (grayed out on these pages): "
               + ", ".join(std.LOCKABLE[k] for k in S.locked if S.vxlan or k not in std.VXLAN_ONLY))

super_n = None
if S.super_spine_counts:
    c1, c2 = st.columns([1, 2], vertical_alignment="center")
    layer = c1.toggle("Add a super spine layer", value=p.super_spines is not None, key=f"ss_on_{p.super_spines}",
                      help="A 5-stage fabric: super spines above the 4 spines. The super spines become the route reflectors.")
    if layer:
        counts = list(S.super_spine_counts)
        super_n = c2.radio("Super spines", counts, horizontal=True,
                           index=counts.index(p.super_spines) if p.super_spines in counts else 0,
                           key=f"ss_n_{p.super_spines}")
    if super_n != p.super_spines and picked == p.standard:
        st.warning("Not saved yet: " + (f"adding a layer of {super_n} super spines (they become the route reflectors)."
                                        if super_n else "removing the super spine layer (the 4 spines become the route reflectors again)."),
                   icon=":material/swap_horiz:")
rr_count = super_n or S.route_reflectors

SRV = {"ip_address": "string", "vrf": "string"}
SYS = {"ip_address": "string", "vrf": "string", "severity": "Int64"}
cols = {
    "ip_address": st.column_config.TextColumn("IP address", required=True),
    "vrf": st.column_config.TextColumn("VRF", default="management"),
    "severity": st.column_config.NumberColumn("Severity", min_value=0, max_value=7, step=1, default=5),
}


def servers(items):
    return [s.to_nac() for s in items]


with st.form("fabric"):
    c1, c2 = st.columns(2)
    name = c1.text_input("Fabric name", p.fabric.name, help="Also the host_vars folder name. Letter first; letters, digits, _ and -.")
    c2.text_input(
        "Fabric type",
        f"{S.fabric_type}: BGP EVPN overlay (iBGP)" if S.vxlan else f"{S.fabric_type}: no VXLAN overlay",
        disabled=True,
        help=LOCKED,
    )
    D = S.defaults
    if S.is_locked("bgp_asn"):
        asn = c1.text_input("BGP ASN", D.bgp_asn, disabled=True, help=LOCKED)
    else:
        asn = c1.text_input("BGP ASN", g.bgp_asn, help="Plain (65001) or asdot (65000.1).")
    mac, om, gc = g.anycast_gateway_mac, g.overlay_mode or "cli", g.greenfield_cleanup or "(not set)"
    if S.vxlan:
        if super_n or S.route_reflectors:
            c2.text_input(
                "Route reflectors",
                f"{super_n} (all {super_n} super spines)" if super_n
                else f"{S.route_reflectors}" + (f" (all {S.spine_count} spines)" if S.spine_count == S.route_reflectors else ""),
                disabled=True,
                help="Locked by the design standard: every spine (or super spine, with a super spine layer) is a "
                     "BGP EVPN route reflector.",
            )
        else:
            rr_count = c2.selectbox("Route reflectors", [2, 4], index=[2, 4].index(g.route_reflectors or 4))
        if S.is_locked("anycast_gateway_mac"):
            mac = c1.text_input("Anycast gateway MAC", D.anycast_gateway_mac, disabled=True, help=LOCKED)
        else:
            mac = c1.text_input("Anycast gateway MAC", g.anycast_gateway_mac, help="Shared by every leaf's SVI gateways.")
        modes = ["cli", "config-profile"]
        if S.is_locked("overlay_mode"):
            om = c2.selectbox("Overlay mode", [D.overlay_mode], disabled=True, help=LOCKED)
        else:
            om = c2.selectbox("Overlay mode", modes, index=modes.index(g.overlay_mode or "cli"))
        gc_opts = ["(not set)", "Enable", "Disable"]
        gc = c1.selectbox(
            "Greenfield cleanup",
            gc_opts,
            index=gc_opts.index(g.greenfield_cleanup or "(not set)"),
            help="Enable removes existing switch config when ND adds the switches (new builds only).",
        )

        st.subheader("Management services", divider="gray")
        st.caption("Up to 4 of each. VRF is usually `management`.")
        s1, s2, s3 = st.columns(3)
        with s1:
            st.markdown("**DNS servers**")
            dns_df = st.data_editor(frame(servers(g.dns_servers), SRV), num_rows="dynamic", column_config=cols, key=key("dns"), use_container_width=True)
        with s2:
            st.markdown("**NTP servers**")
            ntp_df = st.data_editor(frame(servers(g.ntp_servers), SRV), num_rows="dynamic", column_config=cols, key=key("ntp"), use_container_width=True)
        with s3:
            st.markdown("**Syslog servers**")
            sys_df = st.data_editor(frame(servers(g.syslog_servers), SYS), num_rows="dynamic", column_config=cols, key=key("syslog"), use_container_width=True)
    else:
        c2.caption("An External fabric's global settings are just the BGP ASN; switches, interfaces and vPC pairs "
                   "are set on their own pages.")

    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    errors = []
    if S.vxlan:
        dns, e1 = build_rows(records(dns_df), lambda r: ManagementServer(**r), "DNS")
        ntp, e2 = build_rows(records(ntp_df), lambda r: ManagementServer(**r), "NTP")
        syslog, e3 = build_rows(records(sys_df), lambda r: SyslogServer(**r), "Syslog")
        errors += e1 + e2 + e3
    else:  # kept on the project (in case you switch back) but not written for an External fabric
        dns, ntp, syslog = g.dns_servers, g.ntp_servers, g.syslog_servers
    try:
        fabric = Fabric(name=name, type=S.fabric_type)
    except ValidationError as e:
        errors += fmt_errors(e, "Fabric ")
    try:
        ibgp = GlobalIbgp(
            bgp_asn=asn,
            route_reflectors=rr_count or g.route_reflectors,
            anycast_gateway_mac=mac,
            overlay_mode=om,
            greenfield_cleanup=None if gc == "(not set)" else gc,
            dns_servers=dns,
            ntp_servers=ntp,
            syslog_servers=syslog,
        )
    except ValidationError as e:
        errors += fmt_errors(e)
    if errors:
        show_errors(errors)
    else:
        label = f"Fabric saved ({S.label})" if picked != p.standard else "Fabric saved"
        if super_n:
            label += f", with {super_n} super spines"
        q = p.model_copy(update=dict(fabric=fabric, ibgp=ibgp, standard=picked, super_spines=super_n))
        set_project(std.apply_locks(q), label)  # locked standard values always win

section_issues("Fabric")

st.subheader("Clear fabric", divider="red")
gone = clear_summary(p)
with st.popover("Clear all settings…", icon=":material/delete_forever:", disabled=p == clear_fabric(p)):
    st.markdown(f"This deletes **every value** in `{p.fabric.name}` and starts it again from the "
                f"{std.get(p.standard).label} defaults. Only the fabric name and design standard are kept.")
    if gone:
        st.markdown("Deleted: " + ", ".join(gone) + ", plus the global, underlay and management settings.")
    st.caption(f"Files already written to export/{p.fabric.name}/ or a NaC repo aren't touched. "
               "Undo or History can bring the settings back.")
    typed = st.text_input(f"Type **{p.fabric.name}** to confirm", key=f"clear_confirm_{p.fabric.name}")
    if st.button("Delete all values", type="primary", icon=":material/delete_forever:",
                 disabled=typed.strip() != p.fabric.name, key="clear_go"):
        set_project(clear_fabric(p), f"Cleared all settings for {p.fabric.name}")
        st.rerun()
