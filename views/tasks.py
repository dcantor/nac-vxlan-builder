import hashlib

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pydantic import ValidationError

from nacbuilder import hardware as hw
from nacbuilder import standards as std
from nacbuilder.checks import check_project
from nacbuilder.defaults import expand_ports, model_for, model_key, vrf_lite_uplink
from nacbuilder.diffing import compare_projects
from nacbuilder.models import ATTACHABLE_ROLES, Project
from nacbuilder.models.interfaces import SPEEDS
from nacbuilder.portmap import port_picker, render_svg, switch_ports
from nacbuilder.tasks import (
    HostPorts,
    PortSpec,
    network_vlans,
    provision_ports,
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
    PortSettings,
    clear_port,
    port_config,
    set_port,
    settings_of,
)
from nacbuilder.ui import LOCKED, fmt_errors, key, project, records, set_project, show_errors

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


def show_port_map(proj, switches, highlight=frozenset()):
    """Front-panel map: green = enabled in the YAML, red = disabled (enabled: false), gray = not in the YAML."""
    if not switches:
        return
    svg, height = render_svg(proj, switches, highlight)
    components.html(
        '<body style="margin:0;background:#f6f7f9;color:#31333f;border-radius:8px;overflow-x:auto">'
        f'{svg}</body>', height=height + 8, scrolling=False)
    st.caption(":green[■] enabled in the YAML · :red[■] disabled (`enabled: false`) · :gray[■] not in the YAML"
               + (" · blue outline = added or changed by this preview" if highlight else "") + ". Hover a port for details.")


KIND_TEXT = {
    "unused": "Not in the YAML yet.",
    "single": "Configured as its own interface.",
    "member": "A member of {pc}{vpc}; these settings are the port-channel's{both}.",
    "peer_link": "Part of the vPC peer link to {peer}. Change it on the vPC pairs page.",
}


def port_editor(proj, shown):
    """Clickable port map plus a settings panel for the port you click."""
    if not shown:
        return
    sel = st.session_state.get("pp_selected")
    if sel and sel[0] not in shown:
        sel = None
    svg, height = render_svg(proj, shown, selected=sel, clickable=True)
    click = port_picker(svg, height, key=key("pp_click"))
    if click and click.get("click") != st.session_state.get("pp_last_click"):
        st.session_state.pp_last_click = click.get("click")
        st.session_state.pp_selected = (click["switch"], int(click["port"]))
        st.rerun()
    st.caption(":green[■] enabled in the YAML · :red[■] disabled (`enabled: false`) · :gray[■] not in the YAML · "
               ":orange[□] selected. **Click a port** to see and change its settings; hover for details.")
    if not sel:
        return

    sw, n = sel
    cfg = port_config(proj, sw, n)
    cur = settings_of(cfg)
    pc = cfg.interface
    st.markdown(f"#### {cfg.port} on {sw}")
    st.caption(KIND_TEXT[cfg.kind].format(pc=pc.name if pc else "", peer=cfg.peer,
                                          vpc=f" (vPC {pc.vpc_id})" if pc and pc.vpc_id else "",
                                          both=f", on both {sw} and {cfg.peer}" if cfg.kind == "member" and cfg.peer else ""))
    if cfg.kind == "peer_link":
        return
    if not cfg.editable:
        st.info(f"{pc.name} is a {pc.mode} interface. Change it on the Interfaces page.", icon=":material/info:")
        return
    vlans = network_vlans(proj)
    if not vlans:
        st.info("There are no VLANs (networks) in the data model yet, so the port can't be set up here.",
                icon=":material/info:")
        return
    vlan_list = sorted(vlans)
    vrf_of = {x.vlan_id: x.vrf_name for x in proj.networks}

    def vlan_label(v):
        return f"{v} · {vlans[v]}" + (f" ({vrf_of[v]})" if vrf_of.get(v) else "")

    tag = f"{sw}_{n}_{st.session_state.get('editor_ver', 0)}"
    mode = st.radio("Mode", ["access", "trunk"], index=["access", "trunk"].index(cur.mode), horizontal=True,
                    format_func=str.capitalize, key=f"pe_mode_{tag}")
    with st.form(f"pe_{tag}"):
        c1, c2 = st.columns(2)
        enabled = c1.toggle("Enabled (no shutdown)", cur.enabled, help="Off writes enabled: false (red on the map).")
        edge = c2.toggle("Edge port", cur.edge, help="spanning-tree portfast and BPDU guard")
        desc = st.text_input("Description", cur.description or "", placeholder="esx-01")
        access_vlan, allowed, native = None, [], None
        if mode == "access":
            access_vlan = st.selectbox("Access VLAN", vlan_list, format_func=vlan_label,
                                       index=vlan_list.index(cur.access_vlan) if cur.access_vlan in vlan_list else 0)
        else:
            c1, c2 = st.columns([2, 1])
            allowed = c1.multiselect("Tagged (allowed) VLANs", vlan_list, format_func=vlan_label,
                                     default=[v for v in cur.allowed_vlans if v in vlan_list and v != cur.native_vlan])
            natives = [None, *vlan_list]
            native = c2.selectbox("Native VLAN", natives, format_func=lambda v: "(none)" if v is None else vlan_label(v),
                                  index=natives.index(cur.native_vlan) if cur.native_vlan in natives else 0)
        c1, c2 = st.columns(2)
        speed = cur.speed
        if cfg.kind != "member":
            speeds = ["(not set)", *SPEEDS]
            speed = c1.selectbox("Speed", speeds, index=speeds.index(cur.speed) if cur.speed in speeds else 0)
        mtus = ["(not set)", "jumbo", "default"]
        mtu = c2.selectbox("MTU", mtus, index=mtus.index(cur.mtu) if cur.mtu in mtus else 0)
        go = st.form_submit_button("Preview changes", type="primary")
    if go:
        new = PortSettings(mode=mode, enabled=enabled, description=desc, access_vlan=access_vlan,
                           allowed_vlans=allowed, native_vlan=native, edge=edge,
                           speed=None if speed in (None, "(not set)") else speed,
                           mtu=None if mtu == "(not set)" else mtu)
        try:
            what = pc.name if cfg.kind == "member" else cfg.port
            stage(f"Port {what} on {sw}" + (f" and {cfg.peer}" if cfg.kind == "member" and cfg.peer else "")
                  + (": new " if cfg.kind == "unused" else ": change ") + f"{mode}"
                  + ("" if enabled else ", disabled"), set_port(proj, sw, n, new))
        except (ValidationError, ValueError) as e:
            fail(e)
    if cfg.kind != "unused" and st.button("Remove from the YAML", icon=":material/remove_circle:", key=f"pe_rm_{tag}"):
        try:
            where = f"{pc.name}" if cfg.kind == "member" else cfg.port
            stage(f"Port {cfg.port} on {sw}: remove" + (f" from {where}" if cfg.kind == "member" else ""),
                  clear_port(proj, sw, n))
        except ValueError as e:
            fail(e)


if not p.is_vxlan:
    st.info("This fabric uses the Non-VXLAN design: tenant, VRF, VLAN and leaf-pair tasks don't apply. "
            "Decommission is available below.", icon=":material/info:")
    (tab_remove,) = st.tabs(["Decommission"])
else:
    tab_tenant, tab_vrf, tab_vlan, tab_extend, tab_ports, tab_leafs, tab_remove = st.tabs(
        ["New tenant", "Add VRF", "Add VLAN", "Extend to switches", "Provision ports", "Onboard a leaf pair",
         "Decommission"])

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
            lite_up = c2.text_input("Uplink port(s)", vrf_lite_uplink(p), key="addvrf_up")
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
            lite_up = c2.text_input("Uplink port(s)", vrf_lite_uplink(p))
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

# --- provision host ports ------------------------------------------------------------------
if p.is_vxlan:
    with tab_ports:
        vlan_names = network_vlans(p)
        vrf_of = {n.vlan_id: n.vrf_name for n in p.networks}
        if not vlan_names:
            st.info("There are no VLANs (networks) in the data model yet. Ports can only use VLANs defined as "
                    "networks, so add some first (Add VLAN or the Networks page).", icon=":material/info:")
        else:
            st.caption("Access or trunk host ports, as single ports, port-channels or vPC port-channels. VLANs can "
                       "only be picked from the networks in the data model.")

            def vlan_label(v):
                return f"{v} · {vlan_names[v]}" + (f" ({vrf_of[v]})" if vrf_of.get(v) else "")

            c1, c2 = st.columns(2)
            ptype = c1.radio("Interface type", ["access", "trunk"], horizontal=True, key="pp_type",
                             format_func=str.capitalize)
            attach_opts = {"single": "Single ports", "port-channel": "Port-channel", "vpc": "vPC port-channel"}
            pattach = c2.radio("Attach as", list(attach_opts), horizontal=True, key="pp_attach",
                               format_func=attach_opts.get)
            vlan_list = sorted(vlan_names)
            with st.form("ports"):
                pair_key, sws = None, []
                if pattach == "vpc":
                    if not p.vpc_peers:
                        st.warning("There are no vPC pairs yet.")
                    pair_key = st.selectbox("vPC pair", [v.key for v in p.vpc_peers],
                                            format_func=lambda k: k.replace("|", " + "))
                else:
                    sws = st.multiselect("Switches", attachable)
                c1, c2 = st.columns([2, 1])
                ports_txt = c1.text_input("Ports", placeholder="Ethernet1/10-12",
                                          help="Same ports on every switch (both peers for a vPC)")
                bundle = False
                if pattach != "single":
                    bundle = c2.radio("Channels", ["One per port", "One with all ports"], key="pp_bundle") == \
                        "One with all ports"
                access_vlan, allowed, native = None, [], None
                if ptype == "access":
                    access_vlan = st.selectbox("Access VLAN", vlan_list, format_func=vlan_label)
                else:
                    c1, c2 = st.columns([2, 1])
                    allowed = c1.multiselect("Tagged (allowed) VLANs", vlan_list, format_func=vlan_label)
                    native = c2.selectbox("Native VLAN", [None, *vlan_list],
                                          format_func=lambda v: "(none)" if v is None else vlan_label(v),
                                          help="Added to the allowed VLANs automatically")
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                desc = c1.text_input("Description", placeholder="esx-01")
                edge = c2.checkbox("Edge port", value=True, help="spanning-tree portfast and BPDU guard")
                deploy = c3.checkbox("Deploy the VLANs here", value=True,
                                     help="Also deploy these VLANs' networks (and VRFs) to the switches")
                replace = c4.checkbox("Replace existing", value=False)
                go = st.form_submit_button("Preview", type="primary")
            if go:
                try:
                    spec = PortSpec(ports=ports_txt, mode=ptype, switches=sws, vpc_pair=pair_key, attach=pattach,
                                    bundle=bundle, access_vlan=access_vlan, allowed_vlans=allowed, native_vlan=native,
                                    description=desc or None, edge=edge, replace=replace, deploy_networks=deploy)
                    q = provision_ports(p, spec)
                    where = pair_key.replace("|", " + ") if pattach == "vpc" else ", ".join(sws)
                    kind = {"single": "single ports", "port-channel": "port-channel", "vpc": "vPC port-channel"}[pattach]
                    stage(f"Provision {ptype} {kind} {ports_txt} on {where}", q)
                except (ValidationError, ValueError) as e:
                    fail(e)

        st.markdown("**Port map**")
        map_opts = [s.name for s in p.switches if s.role in ATTACHABLE_ROLES] or [s.name for s in p.switches]
        roles = {s.name: s.role for s in p.switches}
        pairs = [[v.peer1, v.peer2] for v in p.vpc_peers if v.peer1 in map_opts and v.peer2 in map_opts]
        default_pair = next((pr for pr in pairs if roles[pr[0]] == "leaf"), pairs[0] if pairs else map_opts[:2])
        shown = st.multiselect("Show switches", map_opts, default=default_pair, key=key("pp_map"))
        port_editor(p, shown)

# --- onboard a leaf pair ------------------------------------------------------------
if p.is_vxlan:
    with tab_leafs:
        onb_role = None
        if p.leaf_roles:
            onb_role = st.radio("Leaf role", p.leaf_roles, horizontal=True, key="onb_role",
                                format_func=lambda r: p.leaf_role_label(r))
        n1, n2 = next_leaf_names(p, leaf_role=onb_role)
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
            leaf_models = hw.models_for("leaf")
            want = model_for(p.role_models, "leaf", onb_role) or hw.suggested().get("leaf")
            fixed = std.locked_model(std.get(p.standard), model_key("leaf", onb_role))
            if fixed:
                want = fixed
                leaf_model = c1.selectbox("Model", [fixed], disabled=True, key="onb_model_locked",
                                          help=LOCKED)
            else:
                leaf_model = c1.selectbox("Model", leaf_models,
                                          index=leaf_models.index(want) if want in leaf_models else 0, key="onb_model")
            peerlink = c2.text_input("Peer-link ports (blank = the model's)", "",
                                     placeholder=", ".join(hw.get(want).peer_link()) if hw.get(want) else "Ethernet1/53, Ethernet1/54")
            st.markdown("**Host ports**: one vPC port-channel per port, same port on both leafs")
            c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
            host = c1.text_input("Ports", placeholder="Ethernet1/1-24")
            mode = c2.selectbox("Mode", ["trunk", "access"])
            access_vlan = c3.number_input("Access VLAN", 1, 4094, 1)
            trunk = c4.text_input("Trunk VLANs", placeholder="2300-2399")
            role_group = f"leaf-{onb_role}" if onb_role and f"leaf-{onb_role}" in p.attach_groups() else None
            join = st.multiselect("Add to attach groups", sorted(p.attach_groups()),
                                  default=[g for g in ("all", role_group) if g and g in p.attach_groups()])
            go = st.form_submit_button("Preview", type="primary")
        if go:
            try:
                hp = HostPorts(host, mode, int(access_vlan), trunk or None) if host.strip() else None
                links = [] if fabric_peering else (expand_ports(peerlink) if peerlink.strip() else None)
                q = onboard_leaf_pair(p, (name1.strip(), name2.strip()), (serial1.strip(), serial2.strip()),
                                      (ip1.strip(), ip2.strip()), int(mgmt_mask), mgmt_gw.strip() or None, links,
                                      fabric_peering, hp, join, model=leaf_model, leaf_role=onb_role)
                stage(f"Onboard {name1.strip()} + {name2.strip()}" + (f" ({p.leaf_role_label(onb_role).lower()})" if onb_role else ""), q)
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
    if pv["label"].startswith(("Provision ", "Port ")):
        before_ports = {(sw.name, pt.number, pt.state, tuple(pt.details)) for sw in p.switches
                        for pt in switch_ports(p, sw.name)}
        touched = {(sw.name, pt.number) for sw in q.switches for pt in switch_ports(q, sw.name)
                   if pt.state != "unused" and (sw.name, pt.number, pt.state, tuple(pt.details)) not in before_ports}
        st.markdown("**Port map after this change**")
        show_port_map(q, sorted({sw for sw, _ in touched}, key=[s.name for s in q.switches].index), touched)
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Apply", type="primary", disabled=pv["base"] != fingerprint(p), use_container_width=True):
        del st.session_state["task_preview"]
        set_project(q, pv["label"])
        st.rerun()
    if c2.button("Discard", use_container_width=True):
        del st.session_state["task_preview"]
        st.rerun()
