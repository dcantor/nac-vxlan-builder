import streamlit as st
from pydantic import ValidationError

from nacbuilder.models import Fabric, GlobalIbgp, ManagementServer, SyslogServer
from nacbuilder.ui import build_rows, fmt_errors, frame, key, project, records, save, section_issues, show_errors

p = project()
g = p.ibgp

st.title("Fabric")
st.caption("Basic settings for an iBGP VXLAN EVPN fabric (Nexus Dashboard 4.2) → `global.nac.yaml`")

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
    c2.text_input("Fabric type", "VXLAN_EVPN (iBGP EVPN)", disabled=True, help="Other fabric types come later.")
    asn = c1.text_input("BGP ASN", g.bgp_asn, help="Plain (65001) or asdot (65000.1).")
    rr = c2.selectbox("Route reflectors", [2, 4], index=[2, 4].index(g.route_reflectors), help="How many spines act as BGP route reflectors.")
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

    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    errors = []
    dns, e1 = build_rows(records(dns_df), lambda r: ManagementServer(**r), "DNS")
    ntp, e2 = build_rows(records(ntp_df), lambda r: ManagementServer(**r), "NTP")
    syslog, e3 = build_rows(records(sys_df), lambda r: SyslogServer(**r), "Syslog")
    errors += e1 + e2 + e3
    try:
        fabric = Fabric(name=name, type="VXLAN_EVPN")
    except ValidationError as e:
        errors += fmt_errors(e, "Fabric ")
    try:
        ibgp = GlobalIbgp(
            bgp_asn=asn,
            route_reflectors=rr,
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
        save("Fabric saved", fabric=fabric, ibgp=ibgp)

section_issues("Fabric")
