import pandas as pd
import streamlit as st
from pydantic import ValidationError

from nacbuilder.defaults import generate_switches
from nacbuilder.models import ROLES, Management, Switch
from nacbuilder.ui import build_rows, fmt_errors, frame, key, project, records, save, section_issues, show_errors

p = project()

st.title("Switches")
st.caption("Spines, leafs and borders with their management addresses → `topology_switches.nac.yaml`")

COLS = {
    "name": "string",
    "role": "string",
    "serial_number": "string",
    "management_ipv4_address": "string",
    "subnet_mask_ipv4": "Int64",
    "default_gateway_v4": "string",
}


def to_row(s: Switch) -> dict:
    m = s.management.to_nac() if s.management else {}
    return {"name": s.name, "role": s.role, "serial_number": s.serial_number, **m}


def from_row(r: dict) -> Switch:
    mgmt = {k: r.pop(k) for k in ("management_ipv4_address", "subnet_mask_ipv4", "default_gateway_v4") if k in r}
    return Switch(**r, management=Management(**mgmt) if mgmt else None)


with st.expander("Quick generate", expanded=not p.switches, icon=":material/bolt:"):
    with st.form("generate"):
        c1, c2, c3, c4 = st.columns(4)
        prefix = c1.text_input("Name prefix", "dc1")
        spines = c2.number_input("Spines", 1, 16, 2)
        leafs = c3.number_input("Leafs", 0, 128, 4)
        borders = c4.number_input("Borders", 0, 16, 0)
        c5, c6, c7 = st.columns(3)
        first_ip = c5.text_input("First management IP", "10.1.1.11", help="Each next switch gets the next address.")
        mask = c6.number_input("Management mask length", 8, 30, 24)
        gw = c7.text_input("Management gateway", "10.1.1.1")
        go = st.form_submit_button("Generate (replaces the table)")
    if go:
        try:
            sw = generate_switches(prefix, spines, leafs, borders, first_ip or None, gw or None, mask)
            save(f"Generated {len(sw)} switches", switches=sw)
        except (ValidationError, ValueError) as e:
            show_errors(fmt_errors(e) if isinstance(e, ValidationError) else [str(e)])

with st.expander("Import CSV", icon=":material/upload_file:"):
    st.caption(f"Columns: {', '.join(COLS)}. Only `name` is required.")
    up = st.file_uploader("CSV file", type=["csv"], key=key("switch_csv"), label_visibility="collapsed")
    if up is not None:
        df = pd.read_csv(up, dtype=str)
        unknown = set(df.columns) - set(COLS)
        if unknown:
            show_errors([f"Unknown column(s): {', '.join(sorted(unknown))}"])
        else:
            sw, errors = build_rows(records(df.reindex(columns=list(COLS))), from_row, "CSV")
            if errors:
                show_errors(errors)
            else:
                save(f"Imported {len(sw)} switches", switches=sw)

with st.form("switches"):
    df = st.data_editor(
        frame([to_row(s) for s in p.switches], COLS),
        num_rows="dynamic",
        use_container_width=True,
        key=key("switches"),
        column_config={
            "name": st.column_config.TextColumn("Name", required=True),
            "role": st.column_config.SelectboxColumn("Role", options=list(ROLES), default="leaf", required=True),
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
