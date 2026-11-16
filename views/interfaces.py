import streamlit as st
from pydantic import ValidationError

from nacbuilder.cabling import canon
from nacbuilder.defaults import expand_ports, vpc_port_channel
from nacbuilder.models import MODES, SPINE_ROLES, Interface
from nacbuilder.models.interfaces import SPEEDS
from nacbuilder.tabular import INTERFACE_COLS, interface_from_row, interface_to_row
from nacbuilder.ui import TABLE_HELP, build_rows, csv_import, fmt_errors, frame, key, project, records, save, section_issues, show_errors

ALL = "All switches"

p = project()

st.title("Interfaces")
st.caption(
    "Host ports, port-channels (including vPC), routed uplinks and sub-interfaces → "
    "`vxlan.topology.switches[].interfaces`"
)

names = [s.name for s in p.switches]
counts = {}
for i in p.interfaces:
    counts[i.mode] = counts.get(i.mode, 0) + 1
cols = st.columns(4)
cols[0].metric("Interfaces", len(p.interfaces))
cols[1].metric("Port-channels", sum(i.is_port_channel for i in p.interfaces))
cols[2].metric("vPC port-channels", len({(p.vpc_peer_of(i.switch).key, i.vpc_id) for i in p.interfaces if i.vpc_id and p.vpc_peer_of(i.switch)}))
cols[3].metric("Routed / sub-interfaces", counts.get("routed", 0) + counts.get("routed_sub", 0) + counts.get("routed_po", 0))

tab_bulk, tab_vpc = st.tabs(["Add host ports", "Add vPC port-channel"])
with tab_bulk:
    with st.form("bulk"):
        sws = st.multiselect("Switches", [s.name for s in p.switches if s.role not in SPINE_ROLES])
        c1, c2 = st.columns([2, 1])
        ports = c1.text_input("Ports", placeholder="Ethernet1/1-24, Ethernet1/30")
        mode = c2.selectbox("Mode", ["access", "trunk", "routed"])
        c1, c2, c3 = st.columns(3)
        access_vlan = c1.number_input("Access VLAN", 1, 4094, 1)
        trunk = c2.text_input("Trunk allowed VLANs", placeholder="2300-2310,2400")
        desc = c3.text_input("Description")
        go = st.form_submit_button("Add ports")
    if go:
        try:
            have = {(i.switch, i.name.lower()) for i in p.interfaces}
            new, skipped = [], []
            for sw in sws:
                for port in expand_ports(ports):
                    if (sw, port.lower()) in have:
                        skipped.append(f"{sw} {port}")
                        continue
                    extra = {"access_vlan": access_vlan} if mode == "access" else {"trunk_allowed_vlans": trunk or None} if mode == "trunk" else {}
                    new.append(Interface(switch=sw, name=port, mode=mode, description=desc or None, **extra))
            if skipped:
                st.warning(f"Skipped existing: {', '.join(skipped[:10])}{' …' if len(skipped) > 10 else ''}")
            if new:
                save(f"Added {len(new)} interface(s)", interfaces=[*p.interfaces, *new])
            elif not skipped:
                show_errors(["Pick at least one switch and some ports."])
        except ValidationError as e:
            show_errors(fmt_errors(e))
        except ValueError as e:
            show_errors([str(e)])

with tab_vpc:
    if not p.vpc_peers:
        st.info("Create vPC pairs first.", icon=":material/info:")
    else:
        with st.form("vpc_po"):
            pair_key = st.selectbox("vPC pair", [v.key for v in p.vpc_peers], format_func=lambda k: k.replace("|", " + "))
            c1, c2, c3 = st.columns(3)
            used_po = [int(i.name.lower().replace("port-channel", "").replace("po", "") or 0) for i in p.interfaces if i.is_port_channel and i.mode != "routed_po"]
            po = c1.number_input("Port-channel number", 1, 4096, max([10, *used_po]) + 1)
            vpc_id = c2.number_input("vPC ID (0 = same as port-channel)", 0, 4096, 0)
            mode = c3.selectbox("Mode", ["trunk", "access"], key="vpc_mode")
            c1, c2 = st.columns(2)
            m1 = c1.text_input("Members on peer 1", placeholder="Ethernet1/1")
            m2 = c2.text_input("Members on peer 2 (blank = same as peer 1)")
            c1, c2, c3 = st.columns(3)
            vlan = c1.number_input("Access VLAN", 1, 4094, 1, key="vpc_access")
            trunk = c2.text_input("Trunk allowed VLANs", placeholder="2300-2310", key="vpc_trunk")
            desc = c3.text_input("Description", key="vpc_desc")
            go = st.form_submit_button("Add vPC port-channel")
        if go:
            try:
                pair = next(v for v in p.vpc_peers if v.key == pair_key)
                members1 = expand_ports(m1)
                members2 = expand_ports(m2) if m2.strip() else members1
                new = vpc_port_channel(pair, int(po), int(vpc_id) or int(po), members1, members2, mode,
                                       access_vlan=int(vlan), trunk_vlans=trunk or None, description=desc or None)
                clash = [f"{i.switch} {i.name}" for i in new if any(j.switch == i.switch and j.name.lower() == i.name.lower() for j in p.interfaces)]
                if clash:
                    show_errors([f"{c} already exists" for c in clash])
                else:
                    save(f"Added port-channel{po} (vPC {int(vpc_id) or int(po)}) on {pair.peer1} and {pair.peer2}",
                         interfaces=[*p.interfaces, *new])
            except ValidationError as e:
                show_errors(fmt_errors(e))
            except ValueError as e:
                show_errors([str(e)])

csv_import("interfaces", "interfaces", INTERFACE_COLS, interface_from_row, required=["switch", "name", "mode"])

st.subheader("Table", divider="gray")
view = st.selectbox("Show", [ALL, *names], key="if_filter")
shown = p.interfaces if view == ALL else p.interfaces_of(view)
if view != ALL:
    spec = p.model_of(view)
    if spec is None:
        st.caption(f"{view} has no hardware model, so its ports aren't checked. Set one on the Switches page.")
    else:
        used = {canon(i.name.split(".")[0]) for i in shown if not i.is_port_channel} | {canon(m) for i in shown for m in i.members}
        pair = p.vpc_peer_of(view)
        if pair:
            used |= {canon(x) for x in (pair.peer1_peerlink_interfaces if pair.peer1 == view else pair.peer2_peerlink_interfaces)}
        free_host = [x for x in spec.host_ports() if canon(x) not in used]
        st.caption(f"**{spec.model}**: {spec.layout()} · {len(free_host)} of {len(spec.host)} host ports free"
                   + (f" (next: {', '.join(free_host[:4])}{'…' if len(free_host) > 4 else ''})" if free_host else ""))
st.caption(TABLE_HELP + (f" New rows default to {view}." if view != ALL else ""))
with st.form("interfaces"):
    df = st.data_editor(
        frame([interface_to_row(i) for i in shown], INTERFACE_COLS),
        num_rows="dynamic",
        width="stretch",
        key=key(f"interfaces_{view}"),
        column_config={
            "switch": st.column_config.SelectboxColumn("Switch", options=sorted(set(names) | {i.switch for i in p.interfaces}),
                                                       required=True, default=None if view == ALL else view),
            "name": st.column_config.TextColumn("Name", required=True, help="Ethernet1/10, port-channel10, Ethernet1/49.100, loopback10"),
            "mode": st.column_config.SelectboxColumn("Mode", options=list(MODES), required=True),
            "description": st.column_config.TextColumn("Description"),
            "access_vlan": st.column_config.NumberColumn("Access VLAN", min_value=1, max_value=4094, step=1),
            "trunk_allowed_vlans": st.column_config.TextColumn("Trunk VLANs", help="10-20,50 or all"),
            "native_vlan": st.column_config.NumberColumn("Native VLAN", min_value=1, max_value=4094, step=1),
            "members": st.column_config.TextColumn("PC members", help="Port-channels only: Ethernet1/1, Ethernet1/2"),
            "vpc_id": st.column_config.NumberColumn("vPC ID", min_value=1, max_value=4096, step=1),
            "ipv4_address": st.column_config.TextColumn("IPv4/len", help="Routed only, e.g. 10.0.0.1/30"),
            "vrf": st.column_config.TextColumn("VRF"),
            "dot1q_id": st.column_config.NumberColumn("dot1q", min_value=1, max_value=4093, step=1),
            "mtu": st.column_config.TextColumn("MTU", help="576-9216, jumbo or default"),
            "speed": st.column_config.SelectboxColumn("Speed", options=list(SPEEDS)),
            "enabled": st.column_config.SelectboxColumn("Enabled", options=["yes", "no"]),
        },
    )
    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    rows = records(df)
    if view != ALL:
        for r in rows:
            if not r.get("switch"):
                r["switch"] = view
    items, errors = build_rows(rows, interface_from_row, "Interface")
    if errors:
        show_errors(errors)
    else:
        rest = [] if view == ALL else [i for i in p.interfaces if i.switch != view]
        save(f"Saved {len(items)} interface(s)", interfaces=[*rest, *items])

section_issues("Interfaces")
