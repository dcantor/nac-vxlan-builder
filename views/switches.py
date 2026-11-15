import streamlit as st
from pydantic import ValidationError

from nacbuilder import hardware as hw
from nacbuilder import standards as std
from nacbuilder.defaults import generate_external_switches, generate_switches
from nacbuilder.models import ROLES
from nacbuilder.tabular import SWITCH_COLS, switch_from_row, switch_to_row
from nacbuilder.ui import TABLE_HELP, build_rows, csv_import, fmt_errors, frame, key, project, records, save, section_issues, show_errors

p = project()

st.title("Switches")
S = std.get(p.standard)
if S.vxlan:
    st.caption(f"{S.label}: spines, leafs and borders with their management addresses → `topology_switches.nac.yaml`")
    counts = {"Super spines": sum(s.role == "super_spine" for s in p.switches)} if p.has_super_spines else {}
    counts |= {"Spines": sum(s.role == "spine" for s in p.switches), "Leafs": sum(s.role == "leaf" for s in p.switches)}
    counts |= {f"{v} borders": sum(s.border_set == k for s in p.switches) for k, v in S.border_sets.items()}
    targets = {"Super spines": p.super_spines, "Spines": S.spine_count}
    targets |= {f"{v} borders": S.borders_per_set for v in S.border_sets.values()}
else:
    st.caption(f"{S.label}: core and edge routers with their management addresses → `topology_switches.nac.yaml`")
    counts = {"Core routers": sum(s.role == "core_router" for s in p.switches),
              "Edge routers": sum(s.role == "edge_router" for s in p.switches),
              "Other roles": sum(s.role not in S.roles for s in p.switches)}
    targets = {"Other roles": 0}
for col, (label, n) in zip(st.columns(len(counts)), counts.items()):
    want = targets.get(label)
    col.metric(label, n, delta=None if want is None or n == want else f"need {want}", delta_color="inverse")

COLS = SWITCH_COLS
to_row = switch_to_row
from_row = switch_from_row

# --- hardware: a Nexus 9300 model per role -----------------------------------------------
if S.vxlan:
    roles = (["super_spine"] if p.has_super_spines else []) + ["spine", "leaf", "border"]
else:
    roles = ["core_router", "edge_router"]
picks_default = {r: p.role_models.get(r) or hw.suggested().get(r) for r in roles}
with st.expander("Hardware: Nexus 9300 models", expanded=not p.role_models, icon=":material/memory:"):
    st.caption("Pick a model per role. Port numbering follows it: spine uplinks, vPC peer links, host ports, VRF-lite "
               "uplinks and the cabling plan, and interfaces are checked against the model's ports. Models are kept "
               "in the project, not written to the YAML. The catalog is `nacbuilder/data/nexus9300.yaml`.")
    with st.form("hardware"):
        picks = {}
        cols = st.columns(len(roles))
        for col, role in zip(cols, roles):
            options = hw.models_for(role)
            cur = picks_default[role] if picks_default[role] in options else options[0]
            picks[role] = col.selectbox(role.replace("_", " ").title(), options, index=options.index(cur),
                                        key=f"hw_{role}")
            col.caption(hw.get(picks[role]).layout())
        overwrite = st.checkbox("Also replace models already set on individual switches", value=False)
        apply = st.form_submit_button("Apply to switches", type="primary")
    if apply:
        changed = 0
        new_sw = []
        for sw in p.switches:
            want = picks.get(sw.role)
            if want and (overwrite or not sw.model) and sw.model != want:
                sw = sw.model_copy(update={"model": want})
                changed += 1
            new_sw.append(sw)
        save(f"Hardware saved; {changed} switch(es) updated", switches=new_sw, role_models={**p.role_models, **picks})

with st.expander("Quick generate", expanded=not p.switches, icon=":material/bolt:"):
    if S.vxlan:
        layer = (f"{p.super_spines} super spines (route reflectors), {S.spine_count} spines"
                 if p.has_super_spines else f"{S.spine_count} spines (route reflectors)")
        st.caption(
            f"Builds the {S.label} layout: {layer}, your leafs, and "
            f"{S.borders_per_set} borders each for {', '.join(S.border_sets)}."
        )
    else:
        st.caption(f"Builds a {S.label}: core routers (`core_router`) and edge routers (`edge_router`).")
    with st.form("generate"):
        c1, c2, c3 = st.columns(3)
        prefix = c1.text_input("Name prefix", "dc1" if S.vxlan else "ext1")
        if S.vxlan:
            leafs = c2.number_input("Leafs", 0, 128, 4)
        else:
            core = c2.number_input("Core routers", 0, 64, 2)
            edge = c3.number_input("Edge routers", 0, 64, 2)
        c5, c6, c7 = st.columns(3)
        first_ip = c5.text_input("First management IP", "10.1.1.11", help="Each next switch gets the next address.")
        mask = c6.number_input("Management mask length", 8, 30, 24)
        gw = c7.text_input("Management gateway", "10.1.1.1")
        go = st.form_submit_button("Generate (replaces the table)")
    if go:
        try:
            if S.vxlan:
                sw = generate_switches(prefix, leafs, first_ip or None, gw or None, mask,
                                       super_spines=p.super_spines if p.has_super_spines else 0,
                                       role_models={**hw.suggested(), **p.role_models})
            else:
                sw = generate_external_switches(prefix, core, edge, first_ip or None, gw or None, mask,
                                                role_models={**hw.suggested(), **p.role_models})
            save(f"Generated {len(sw)} switches", switches=sw)
        except (ValidationError, ValueError) as e:
            show_errors(fmt_errors(e) if isinstance(e, ValidationError) else [str(e)])

csv_import("switches", "switches", COLS, from_row, required=["name"])

st.caption(TABLE_HELP)
with st.form("switches"):
    df = st.data_editor(
        frame([to_row(s) for s in p.switches], COLS),
        num_rows="dynamic",
        use_container_width=True,
        key=key("switches"),
        column_config={
            "name": st.column_config.TextColumn("Name", required=True),
            "role": st.column_config.SelectboxColumn("Role", options=list(ROLES), default="leaf", required=True),
            "border_set": st.column_config.SelectboxColumn(
                "Border set", options=list(std.BORDER_SETS), help="Borders only: client, internal or external pair"
            ),
            "model": st.column_config.SelectboxColumn(
                "Model", options=sorted(set(hw.catalog()) | {x.model for x in p.switches if x.model}),
                help="Nexus 9300 model; port numbering and checks follow it"
            ),
            "serial_number": st.column_config.TextColumn("Serial number", help="Required by ND to add the switch"),
            "management_ipv4_address": st.column_config.TextColumn("Mgmt IPv4"),
            "subnet_mask_ipv4": st.column_config.NumberColumn("Mask", min_value=8, max_value=30, step=1),
            "default_gateway_v4": st.column_config.TextColumn("Mgmt gateway"),
        },
    )
    submitted = st.form_submit_button("Save", type="primary")

if submitted:
    sw, errors = build_rows(records(df), from_row, "Switch")
    if errors:
        show_errors(errors)
    else:
        save(f"Saved {len(sw)} switches", switches=sw)

section_issues("Switches")
