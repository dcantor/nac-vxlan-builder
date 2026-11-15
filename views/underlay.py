import streamlit as st
from pydantic import ValidationError

from nacbuilder import standards as std
from nacbuilder.models import Underlay, UnderlayGeneral, UnderlayIpv4, UnderlayMulticast, UnderlayOspf
from nacbuilder.ui import fmt_errors, project, save, section_issues, show_errors

u = project().underlay
g, v4, ospf, mc = u.general, u.ipv4, u.ospf, u.multicast

st.title("Underlay")
st.caption("Routing protocol, replication and IP pools for the fabric underlay → `underlay.nac.yaml`")


def idx(options, value):
    return options.index(value)


with st.form("underlay"):
    st.subheader("General", divider="gray")
    c1, c2, c3 = st.columns(3)
    c1.text_input("Routing protocol", "OSPF", disabled=True, help="Fixed by the design standard.")
    reps = ["multicast", "ingress"]
    rep = c2.selectbox("BUM replication", reps, index=idx(reps, g.replication_mode), help="Multicast needs RPs on the spines; ingress uses head-end replication.")
    tag = c3.text_input("Routing protocol tag", g.underlay_routing_protocol_tag)
    c1, c2, c3, c4 = st.columns(4)
    lo_rt = c1.number_input("Routing loopback ID", 0, 1023, g.underlay_routing_loopback_id)
    lo_vtep = c2.number_input("VTEP loopback ID", 0, 1023, g.underlay_vtep_loopback_id)
    mtu_fab = c3.number_input("Fabric interface MTU", 576, 9216, g.intra_fabric_interface_mtu)
    mtu_host = c4.number_input("Host interface MTU", 1500, 9216, g.layer2_host_interface_mtu)
    unshut = st.checkbox("Bring host interfaces up (no shutdown)", g.unshut_host_interfaces)

    st.subheader("IPv4 addressing", divider="gray")
    c1, c2 = st.columns(2)
    nums = ["p2p", "unnumbered"]
    numbering = c1.selectbox("Fabric link numbering", nums, index=idx(nums, v4.fabric_interface_numbering))
    mask = c2.selectbox("Fabric link mask", [30, 31], index=idx([30, 31], v4.subnet_mask))
    c1, c2 = st.columns(2)
    rt_range = c1.text_input("Routing loopback range", str(v4.underlay_routing_loopback_ip_range))
    vtep_range = c2.text_input("VTEP loopback range", str(v4.underlay_vtep_loopback_ip_range))
    link_range = c1.text_input("Fabric link subnet range", str(v4.underlay_subnet_ip_range))
    rp_range = c2.text_input("RP loopback range (multicast only)", str(v4.underlay_rp_loopback_ip_range))

    st.subheader("OSPF", divider="gray")
    c1, c2, c3, c4 = st.columns(4)
    area = c1.text_input("Area ID", ospf.area_id)
    auth = c2.checkbox("Authentication", ospf.authentication_enable)
    key_id = c3.number_input("Key ID", 0, 255, ospf.authentication_key_id)
    auth_key = c4.text_input("Key (ND-encrypted 3DES)", ospf.authentication_key, type="password")

    st.subheader("Multicast", divider="gray")
    st.caption("Used only with multicast replication.")
    c1, c2, c3, c4 = st.columns(4)
    rps = c1.selectbox("Rendezvous points", [2, 4], index=idx([2, 4], mc.rendezvous_points))
    rp_modes = ["asm", "bidir"]
    rp_mode = c2.selectbox("RP mode", rp_modes, index=idx(rp_modes, mc.rp_mode))
    rp_lo = c3.number_input("RP loopback ID", 0, 1023, mc.underlay_rp_loopback_id)
    rp_prim = c4.number_input("Primary (phantom) RP loopback ID", 0, 1023, mc.underlay_primary_rp_loopback_id, help="Only used in bidir mode.")

    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    try:
        new = Underlay(
            general=UnderlayGeneral(
                routing_protocol=std.UNDERLAY_PROTOCOL,
                replication_mode=rep,
                underlay_routing_protocol_tag=tag,
                underlay_routing_loopback_id=lo_rt,
                underlay_vtep_loopback_id=lo_vtep,
                intra_fabric_interface_mtu=mtu_fab,
                layer2_host_interface_mtu=mtu_host,
                unshut_host_interfaces=unshut,
            ),
            ipv4=UnderlayIpv4(
                fabric_interface_numbering=numbering,
                subnet_mask=mask,
                underlay_routing_loopback_ip_range=rt_range,
                underlay_vtep_loopback_ip_range=vtep_range,
                underlay_subnet_ip_range=link_range,
                underlay_rp_loopback_ip_range=rp_range,
            ),
            ospf=UnderlayOspf(area_id=area, authentication_enable=auth, authentication_key_id=key_id, authentication_key=auth_key),
            multicast=UnderlayMulticast(rendezvous_points=rps, rp_mode=rp_mode, underlay_rp_loopback_id=rp_lo, underlay_primary_rp_loopback_id=rp_prim),
        )
        save("Underlay saved", underlay=new)
    except ValidationError as e:
        show_errors(fmt_errors(e))

section_issues("Underlay")
