import re
from ipaddress import IPv4Network

import pandas as pd
import streamlit as st

from nacbuilder import hardware as hw
from nacbuilder import standards as std
from nacbuilder.checks import check_project
from nacbuilder.models import LEAF_ROLE_RE, ROLES, Project
from nacbuilder.models.fabric import validate_asn, validate_mac
from nacbuilder.tabular import records
from nacbuilder.ui import project

st.title("Design standards")
st.error(
    "**For developers only.** This page changes the rules every fabric is checked against and the defaults new "
    "fabrics start with, for everyone using this copy of the app. Changes are saved to "
    "`nacbuilder/data/standards.yaml`: review the diff and commit it like code. Network engineers building "
    "fabrics should not need this page.",
    icon=":material/developer_mode:",
)
st.caption(
    ("Using **customised** standards from `nacbuilder/data/standards.yaml`." if std.is_customised()
     else "Using the **built-in** standards (no `nacbuilder/data/standards.yaml` yet).")
)
unlocked = st.checkbox("I understand: let me edit the design standards", key="std_unlock")

NONE = "(not enforced)"
MODEL_ROLES = ["spine", "super_spine", "leaf", "border", "core_router", "edge_router"]


def problems_for(key: str, form: dict) -> list[str]:
    out = []
    try:
        validate_asn(form["bgp_asn"])
    except ValueError as e:
        out.append(f"BGP ASN: {e}")
    try:
        validate_mac(form["anycast_gateway_mac"])
    except ValueError as e:
        out.append(f"Anycast gateway MAC: {e}")
    for fld in ("routing_loopback_range", "vtep_loopback_range", "rp_loopback_range", "fabric_link_range"):
        try:
            IPv4Network(form[fld])
        except ValueError as e:
            out.append(f"{fld.replace('_', ' ')}: {e}")
    for k in form["border_sets"]:
        if not re.fullmatch(LEAF_ROLE_RE, k):
            out.append(f"Border set key '{k}' must be lowercase letters, digits, - or _")
    try:
        Project(leaf_roles=form["leaf_roles"])
    except ValueError as e:
        out.append(f"Leaf roles: {e}")
    if form["fabric_type"] == "VXLAN_EVPN" and form["spine_count"] and form["route_reflectors"] and \
            form["route_reflectors"] > form["spine_count"] and not form["super_spine_counts"]:
        out.append("Route reflectors can't exceed the spine count (without a super spine layer).")
    return out


tabs = st.tabs([std.get(k).label for k in std.KEYS])
for tab, key in zip(tabs, std.KEYS):
    S = std.get(key)
    D = S.defaults
    with tab, st.form(f"std_{key}"):
        st.subheader("Identity", divider="gray")
        c1, c2 = st.columns([1, 3])
        label = c1.text_input("Name", S.label, disabled=not unlocked)
        summary = c2.text_input("Summary (shown on the Fabric page)", S.summary, disabled=not unlocked)

        st.subheader("Constraints", divider="gray")
        st.caption("Rules the checks enforce for fabrics using this standard. '(not enforced)' or 0 turns a rule off.")
        c1, c2, c3, c4 = st.columns(4)
        ftype = c1.selectbox("Fabric type", list(std.FABRIC_TYPES), index=list(std.FABRIC_TYPES).index(S.fabric_type),
                             disabled=not unlocked, help="External = Non-VXLAN (no underlay, VRFs, networks)")
        u_opts = [NONE, *std.UNDERLAY_PROTOCOLS]
        underlay = c2.selectbox("Underlay protocol", u_opts, index=u_opts.index(S.underlay_protocol or NONE),
                                disabled=not unlocked)
        spines = c3.number_input("Spines (0 = any)", 0, 16, S.spine_count or 0, disabled=not unlocked)
        rr_opts = [NONE, 2, 4]
        rr = c4.selectbox("Route reflectors", rr_opts, index=rr_opts.index(S.route_reflectors or NONE),
                          disabled=not unlocked)
        c1, c2 = st.columns(2)
        supers = c1.multiselect("Super spine layer sizes (empty = no super spine option)", [2, 4],
                                default=list(S.super_spine_counts), disabled=not unlocked)
        roles = c2.multiselect("Allowed switch roles (empty = any)", list(ROLES), default=list(S.roles or ()),
                               disabled=not unlocked)
        c1, c2 = st.columns([3, 1])
        bdf = c1.data_editor(
            pd.DataFrame({"key": list(S.border_sets), "label": list(S.border_sets.values())}, dtype="string"),
            num_rows="dynamic", use_container_width=True, key=f"bsets_{key}", disabled=not unlocked,
            column_config={"key": st.column_config.TextColumn("Border set key", required=True),
                           "label": st.column_config.TextColumn("Label", required=True)},
        )
        per_set = c2.number_input("Borders per set", 0, 8, S.borders_per_set, disabled=not unlocked)

        st.subheader("Defaults", divider="gray")
        st.caption("What a new fabric with this standard starts with (sidebar → New), and the pools new VRFs and "
                   "networks are numbered from.")
        c1, c2, c3, c4 = st.columns(4)
        asn = c1.text_input("BGP ASN", D.bgp_asn, disabled=not unlocked)
        mac = c2.text_input("Anycast gateway MAC", D.anycast_gateway_mac, disabled=not unlocked)
        om = c3.selectbox("Overlay mode", ["cli", "config-profile"], index=["cli", "config-profile"].index(D.overlay_mode),
                          disabled=not unlocked)
        rep = c4.selectbox("Replication", ["multicast", "ingress"], index=["multicast", "ingress"].index(D.replication_mode),
                           disabled=not unlocked)
        c1, c2, c3, c4, c5 = st.columns(5)
        lo = c1.text_input("Routing loopbacks", D.routing_loopback_range, disabled=not unlocked)
        vtep = c2.text_input("VTEP loopbacks", D.vtep_loopback_range, disabled=not unlocked)
        rp = c3.text_input("RP loopbacks", D.rp_loopback_range, disabled=not unlocked)
        links = c4.text_input("Fabric links", D.fabric_link_range, disabled=not unlocked)
        mask = c5.selectbox("Link mask", [30, 31], index=[30, 31].index(D.subnet_mask), disabled=not unlocked)
        c1, c2, c3, c4 = st.columns(4)
        l3 = c1.number_input("First L3 VNI (VRFs)", 1, 16777214, D.l3_vni_start, disabled=not unlocked)
        l2 = c2.number_input("First L2 VNI (networks)", 1, 16777214, D.l2_vni_start, disabled=not unlocked)
        vv = c3.number_input("First VRF VLAN", 2, 4094, D.vrf_vlan_start, disabled=not unlocked)
        nv = c4.number_input("First network VLAN", 2, 4094, D.network_vlan_start, disabled=not unlocked)
        leaf_roles = st.text_input("Default leaf roles (comma separated)", ", ".join(D.leaf_roles),
                                   placeholder="compute, storage", disabled=not unlocked)
        st.markdown("Default hardware models")
        mcols = st.columns(len(MODEL_ROLES))
        models = {}
        for col, role in zip(mcols, MODEL_ROLES):
            opts = ["(none)", *hw.models_for(role)]
            cur = D.role_models.get(role) or "(none)"
            models[role] = col.selectbox(role.replace("_", " "), opts, index=opts.index(cur) if cur in opts else 0,
                                         key=f"m_{key}_{role}", disabled=not unlocked)

        save_it = st.form_submit_button("Save standard", type="primary", disabled=not unlocked)

    if save_it:
        border_sets = {r["key"].strip().lower(): r["label"].strip() for r in records(bdf) if r.get("key") and r.get("label")}
        form = dict(bgp_asn=asn, anycast_gateway_mac=mac, routing_loopback_range=lo, vtep_loopback_range=vtep,
                    rp_loopback_range=rp, fabric_link_range=links, border_sets=border_sets, leaf_roles=leaf_roles,
                    fabric_type=ftype, spine_count=int(spines), route_reflectors=None if rr == NONE else rr,
                    super_spine_counts=supers)
        problems = problems_for(key, form)
        with tab:
            if problems:
                st.error("Not saved:\n\n" + "\n".join(f"- {x}" for x in problems))
            else:
                new = std.replace(
                    S, label=label.strip() or S.label, summary=summary.strip(), fabric_type=ftype,
                    underlay_protocol=None if underlay == NONE else underlay, spine_count=int(spines) or None,
                    route_reflectors=None if rr == NONE else rr, super_spine_counts=supers, roles=roles or None,
                    border_sets=border_sets, borders_per_set=int(per_set),
                    defaults=dict(bgp_asn=validate_asn(asn), anycast_gateway_mac=validate_mac(mac), overlay_mode=om,
                                  replication_mode=rep, subnet_mask=mask, routing_loopback_range=lo,
                                  vtep_loopback_range=vtep, rp_loopback_range=rp, fabric_link_range=links,
                                  l3_vni_start=int(l3), l2_vni_start=int(l2), vrf_vlan_start=int(vv),
                                  network_vlan_start=int(nv), leaf_roles=Project(leaf_roles=leaf_roles).leaf_roles,
                                  role_models={r: m for r, m in models.items() if m != "(none)"}),
                )
                std.save({**std.STANDARDS, key: new})
                st.session_state.flash = f"Saved the {new.label} standard to nacbuilder/data/standards.yaml"
                st.rerun()

st.subheader("Effect on the open fabric", divider="gray")
p = project()
issues = check_project(p)
st.caption(f"`{p.fabric.name}` uses **{std.get(p.standard).label}**: "
           f"{sum(i.level == 'error' for i in issues)} errors, {sum(i.level == 'warning' for i in issues)} warnings "
           "under the current standards.")

with st.expander("standards.yaml", icon=":material/code:"):
    st.code(std.dump(std.STANDARDS), language="yaml")

if std.is_customised():
    with st.popover("Restore built-in standards", disabled=not unlocked):
        st.write("Delete `nacbuilder/data/standards.yaml` and go back to the built-in standards?")
        if st.button("Yes, restore", type="primary", key="std_restore"):
            std.restore_builtin()
            st.session_state.flash = "Restored the built-in design standards"
            st.rerun()
