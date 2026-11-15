import streamlit as st
from pydantic import ValidationError

from nacbuilder.defaults import apply_vrf_lite_plan, build_vrf_lite
from nacbuilder.tasks import remove_vrf_lite
from nacbuilder.ui import fmt_errors, project, save, section_issues, show_errors

BORDER_ROLES = ("border", "border_spine", "border_gateway", "border_gateway_spine")

p = project()

st.title("VRF-lite")
st.caption(
    "Hand VRFs off to WAN routers or firewalls from the border switches: eBGP over dot1q sub-interfaces "
    "→ `vxlan.overlay_extensions.vrf_lites` plus the sub-interfaces in the topology."
)

borders = [s for s in p.switches if s.role in BORDER_ROLES]
external = [s.name for s in borders if s.border_set == "external"]
if not p.vrfs or not borders:
    st.info("Add at least one VRF and some border switches first.", icon=":material/info:")
else:
    with st.expander("Add a VRF-lite handoff", expanded=not p.vrf_lites, icon=":material/add_link:"):
        with st.form("vrf_lite"):
            c1, c2 = st.columns(2)
            vrf = c1.selectbox("VRF", [v.name for v in p.vrfs])
            name = c2.text_input("Profile name (blank = <VRF>-vrf-lite)")
            switches = st.multiselect(
                "Border switches", [s.name for s in borders], default=external,
                help="Defaults to the external border pair.",
            )
            c1, c2, c3 = st.columns(3)
            uplinks = c1.text_input("Uplink port(s) on each switch", "Ethernet1/49",
                                    help="Comma separated if a switch has more than one uplink; same ports on every switch")
            dot1q = c2.number_input("dot1q tag (0 = the VRF's VLAN ID)", 0, 4093, 0)
            remote_as = c3.number_input("Neighbor ASN", 1, 4294967295, 65500)
            c1, c2 = st.columns(2)
            pool = c1.text_input("Link subnet pool", "10.254.0.0/24", help="Each uplink gets the next free subnet")
            prefix = c2.radio("Link subnet size", [30, 31], horizontal=True, format_func=lambda n: f"/{n}")
            st.caption("If the VRF's attach group is shared with other VRFs or networks, the VRF gets its own "
                       "copy of the group with these borders added, so nothing else is deployed to them.")
            go = st.form_submit_button("Create", type="primary")
        if go:
            try:
                vrf_obj = next(v for v in p.vrfs if v.name == vrf)
                ports = [x.strip() for x in uplinks.split(",") if x.strip()]
                if not switches or not ports:
                    raise ValueError("pick at least one switch and one uplink port")
                plan = build_vrf_lite(p, vrf, {s: ports for s in switches}, int(dot1q) or vrf_obj.vlan_id, pool, int(prefix),
                                      int(remote_as), name or None)
                q = apply_vrf_lite_plan(p, plan)
                save(f"Created {plan.lite.name}: {len(plan.links)} link(s)", vrf_lites=q.vrf_lites,
                     interfaces=q.interfaces, attachments=q.attachments, vrfs=q.vrfs)
            except ValidationError as e:
                show_errors(fmt_errors(e))
            except ValueError as e:
                show_errors([str(e)])

ifs = {(i.switch, i.name): i for i in p.interfaces}
for lite in p.vrf_lites:
    with st.expander(f"**{lite.name}**: VRF `{lite.vrf}` on {', '.join(s.name for s in lite.switches)}", expanded=True):
        rows = []
        for s in lite.switches:
            peers = s.bgp_peers
            for n, if_name in enumerate(s.interfaces):
                i = ifs.get((s.name, if_name))
                peer = peers[n] if n < len(peers) else None
                rows.append({
                    "switch": s.name,
                    "interface": if_name,
                    "dot1q": i.dot1q_id if i else None,
                    "local IP": str(i.ipv4_address) if i and i.ipv4_address else "",
                    "neighbor": str(peer.address) if peer else "",
                    "neighbor ASN": peer.remote_as if peer else None,
                })
            for peer in peers[len(s.interfaces):]:
                rows.append({"switch": s.name, "interface": "", "neighbor": str(peer.address), "neighbor ASN": peer.remote_as})
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("Edit addresses and tags on the Interfaces page. To change the profile, delete it and add it again.")
        c1, c2 = st.columns([2, 1], vertical_alignment="center")
        drop_ifs = c1.checkbox("Also delete its sub-interfaces", value=True, key=f"drop_ifs_{lite.name}")
        if c2.button("Delete", key=f"del_{lite.name}", icon=":material/delete:", use_container_width=True):
            q = remove_vrf_lite(p, lite.name, drop_interfaces=drop_ifs)
            save(f"Deleted {lite.name}", vrf_lites=q.vrf_lites, interfaces=q.interfaces)

section_issues("VRF-lite")
