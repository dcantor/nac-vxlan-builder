import streamlit as st
from pydantic import ValidationError

from nacbuilder import standards as std
from nacbuilder.models import Fabric, GlobalIbgp, ManagementServer, SyslogServer
from nacbuilder.ui import build_rows, fmt_errors, frame, key, project, records, save, section_issues, show_errors

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
        help="Set by the design standard.",
    )
    asn = c1.text_input("BGP ASN", g.bgp_asn, help="Plain (65001) or asdot (65000.1).")
    mac, om, gc = g.anycast_gateway_mac, g.overlay_mode or "cli", g.greenfield_cleanup or "(not set)"
    if S.vxlan:
        c2.text_input(
            "Route reflectors",
            f"{super_n} (all {super_n} super spines)" if super_n else f"{S.route_reflectors} (all {S.spine_count} spines)",
            disabled=True,
            help="Fixed by the design standard: every spine (or super spine, with a super spine layer) is a "
                 "BGP EVPN route reflector.",
        )
        mac = c1.text_input("Anycast gateway MAC", g.anycast_gateway_mac, help="Shared by every leaf's SVI gateways.")
        modes = ["cli", "config-profile"]
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
        save(label, fabric=fabric, ibgp=ibgp, standard=picked, super_spines=super_n)

section_issues("Fabric")
