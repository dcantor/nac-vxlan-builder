import streamlit as st
from pydantic import ValidationError

from nacbuilder import hardware as hw
from nacbuilder import standards as std
from nacbuilder.defaults import generate_external_switches, generate_switches, model_key
from nacbuilder.models import ROLES, Project
from nacbuilder.tabular import SWITCH_COLS, switch_from_row, switch_to_row
from nacbuilder.standards import locked_model
from nacbuilder.ui import LOCKED, TABLE_HELP, build_rows, csv_import, fmt_errors, frame, key, project, records, save, section_issues, set_project, show_errors

p = project()

st.title("Switches")
S = std.get(p.standard)
if S.vxlan:
    st.caption(f"{S.label}: spines, leafs and borders with their management addresses → `topology_switches.nac.yaml`")
    counts = {"Super spines": sum(s.role == "super_spine" for s in p.switches)} if p.has_super_spines else {}
    counts |= {"Spines": sum(s.role == "spine" for s in p.switches)}
    if p.leaf_roles:
        counts |= {p.leaf_role_label(r): sum(s.role == "leaf" and s.leaf_role == r for s in p.switches) for r in p.leaf_roles}
    else:
        counts |= {"Leafs": sum(s.role == "leaf" for s in p.switches)}
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

# --- leaf roles (compute, storage, ...) ----------------------------------------------------
if S.vxlan:
    with st.expander(f"Leaf roles{': ' + ', '.join(p.leaf_roles) if p.leaf_roles else ''}",
                     expanded=False, icon=":material/category:"):
        st.caption("Optional sub-roles for leafs, such as compute and storage. Each leaf gets one (Leaf role column). "
                   "Quick generate, hardware models, vPC pairing, attach groups and the diagram then work per leaf "
                   "role. Leaf roles are kept in the project, not written to the YAML.")
        lr_locked = S.is_locked("leaf_roles")
        with st.form("leaf_roles"):
            roles_txt = st.text_input("Leaf roles (comma separated; blank = none)",
                                      ", ".join(S.defaults.leaf_roles if lr_locked else p.leaf_roles),
                                      placeholder="compute, storage", disabled=lr_locked,
                                      help=LOCKED if lr_locked else None)
            set_roles = st.form_submit_button("Save leaf roles", disabled=lr_locked)
        if set_roles:
            try:
                new_roles = Project(leaf_roles=roles_txt).leaf_roles
                save(f"Leaf roles: {', '.join(new_roles) or 'none'}", leaf_roles=new_roles)
            except ValidationError as e:
                show_errors(fmt_errors(e))

# --- hardware: a Nexus 9300 model per role -----------------------------------------------
if S.vxlan:
    leaf_keys = [model_key("leaf", r) for r in p.leaf_roles] or ["leaf"]
    roles = (["super_spine"] if p.has_super_spines else []) + ["spine", *leaf_keys, "border"]
else:
    roles = ["core_router", "edge_router"]
picks_default = {r: p.role_models.get(r) or p.role_models.get(r.split(":")[0]) or hw.suggested().get(r.split(":")[0])
                 for r in roles}
with st.expander("Hardware: Nexus 9300 models", expanded=not p.role_models, icon=":material/memory:"):
    st.caption("Pick a model per role. Port numbering follows it: spine uplinks, vPC peer links, host ports, VRF-lite "
               "uplinks and the cabling plan, and interfaces are checked against the model's ports. Models are kept "
               "in the project, not written to the YAML. The catalog is `nacbuilder/data/nexus9300.yaml`.")
    with st.form("hardware"):
        picks = {}
        cols = st.columns(len(roles))
        for col, role in zip(cols, roles):
            options = hw.models_for(role.split(":")[0])
            label = p.leaf_role_label(role.split(":")[1]) if ":" in role else role.replace("_", " ").title()
            fixed = locked_model(S, role)
            if fixed:
                picks[role] = col.selectbox(label, [fixed], disabled=True, key=f"hw_{role}_locked", help=LOCKED)
            else:
                cur = picks_default[role] if picks_default[role] in options else options[0]
                picks[role] = col.selectbox(label, options, index=options.index(cur), key=f"hw_{role}")
            col.caption(hw.get(picks[role]).layout())
        overwrite = st.checkbox("Also replace models already set on individual switches", value=False)
        apply = st.form_submit_button("Apply to switches", type="primary")
    if apply:
        changed = 0
        new_sw = []
        for sw in p.switches:
            want = picks.get(model_key(sw.role, sw.leaf_role)) or picks.get(sw.role)
            if want and (overwrite or not sw.model) and sw.model != want:
                sw = sw.model_copy(update={"model": want})
                changed += 1
            new_sw.append(sw)
        save(f"Hardware saved; {changed} switch(es) updated", switches=new_sw, role_models={**p.role_models, **picks})

locked_models = dict(S.defaults.role_models) if S.is_locked("role_models") else {}
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
        if S.vxlan and p.leaf_roles:
            per_role = {}
            for n, r in enumerate(p.leaf_roles):
                per_role[r] = (c2 if n % 2 == 0 else c3).number_input(p.leaf_role_label(r), 0, 128, 4 if n == 0 else 2,
                                                                       key=f"gen_{r}")
            leafs = per_role
        elif S.vxlan:
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
                sw = generate_switches(prefix, leafs, first_ip or None, gw or None, mask, standard=p.standard,
                                       super_spines=p.super_spines if p.has_super_spines else 0,
                                       role_models={**hw.suggested(), **p.role_models, **locked_models})
            else:
                sw = generate_external_switches(prefix, core, edge, first_ip or None, gw or None, mask,
                                                role_models={**hw.suggested(), **p.role_models, **locked_models})
            set_project(std.apply_locks(p.model_copy(update={"switches": sw}), only={"role_models"}), f"Generated {len(sw)} switches")
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
            "role": st.column_config.SelectboxColumn(
                "Role", options=list(S.roles or ROLES), default=(S.roles or ("leaf",))[0], required=True,
                help=f"Limited by the design standard to {', '.join(S.roles)}" if S.roles else None),
            "border_set": st.column_config.SelectboxColumn(
                "Border set", options=list(S.border_sets), help=f"Borders only: {', '.join(S.border_sets) or 'none in this standard'}"
            ),
            "leaf_role": st.column_config.SelectboxColumn(
                "Leaf role", options=sorted(set(p.leaf_roles) | {x.leaf_role for x in p.switches if x.leaf_role}),
                help="Leafs only: compute, storage, ... (define them under Leaf roles)"
            ),
            "model": st.column_config.SelectboxColumn(
                "Model", options=sorted(set(hw.catalog()) | {x.model for x in p.switches if x.model}),
                help=LOCKED if locked_models else "Nexus 9300 model; port numbering and checks follow it",
                disabled=bool(locked_models),
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
        set_project(std.apply_locks(p.model_copy(update={"switches": sw}), only={"role_models"}), f"Saved {len(sw)} switches")

section_issues("Switches")
