import pandas as pd
import streamlit as st

from nacbuilder.cabling import LINK_COLUMNS, PORT_COLUMNS, UplinkPlan, build_cabling, to_csv_zip, to_xlsx, uplink_plan_for
from nacbuilder.defaults import expand_ports
from nacbuilder.models import SPINE_ROLES
from nacbuilder.ui import project

p = project()

st.title("Cabling plan")
st.caption("What plugs into what, port by port: vPC peer links, host ports and port-channels, VRF-lite uplinks, "
           "and a planned spine-leaf layout. Export it for the install team.")

if not p.switches:
    st.info("Add switches first.", icon=":material/info:")
    st.stop()

n_spines = sum(s.role in SPINE_ROLES and s.role != "super_spine" for s in p.switches)
with st.expander("Spine-leaf links (planned)", expanded=True, icon=":material/cable:"):
    st.caption("Nexus Dashboard discovers fabric links, so they aren't in the YAML. This lays them out by a simple rule: "
               "uplink k on every leaf/border goes to spine k, and each spine uses the next port per leaf "
               "(leafs first, then borders).")
    c1, c2, c3 = st.columns([1, 2, 2])
    include = c1.toggle("Include", value=True)
    from_models = c1.toggle("Use each switch's model", value=any(x.model for x in p.switches),
                            help="Ports come from each switch's Nexus 9300 model; the fields here are the fallback "
                                 "for switches without a model.")
    default_ups = ", ".join(uplink_plan_for(p).leaf_uplinks)
    ups_txt = c2.text_input(f"Leaf/border uplink ports (one per spine, {n_spines} spines)", default_ups)
    first = c3.text_input("First spine downlink port", "Ethernet1/1")

n_supers = sum(s.role == "super_spine" for s in p.switches)
spine_ups_txt, super_first = "", "Ethernet1/1"
if n_supers:
    with st.expander("Super spine links (planned)", expanded=True, icon=":material/cable:"):
        st.caption("Uplink k on every spine goes to super spine k; each super spine uses the next port per spine.")
        c1, c2 = st.columns(2)
        spine_ups_txt = c1.text_input(f"Spine uplink ports (one per super spine, {n_supers} super spines)",
                                      ", ".join(uplink_plan_for(p).spine_uplinks))
        super_first = c2.text_input("First super spine downlink port", "Ethernet1/1")

try:
    uplinks = UplinkPlan(expand_ports(ups_txt), first, expand_ports(spine_ups_txt) if spine_ups_txt.strip() else [],
                         super_first, from_models=from_models) if include else None
    plan = build_cabling(p, uplinks)
except ValueError as e:
    st.error(str(e))
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cables", len(plan.links))
c2.metric("Planned fabric links", sum(r["source"] == "planned" for r in plan.links))
c3.metric("Ports in use", len(plan.ports))
c4.metric("Conflicts", len(plan.conflicts))
if plan.conflicts:
    st.error("Port conflicts:\n\n" + "\n".join(f"- {c}" for c in plan.conflicts))

c1, c2, _ = st.columns([1, 1, 2])
c1.download_button("Download Excel", to_xlsx(plan, p.fabric.name), file_name=f"{p.fabric.name}-cabling.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/table:",
                   type="primary", width="stretch")
c2.download_button("Download CSV (zip)", to_csv_zip(plan, p.fabric.name), file_name=f"{p.fabric.name}-cabling-csv.zip",
                   mime="application/zip", icon=":material/download:", width="stretch")

tab_links, tab_ports, tab_vpc, tab_lite = st.tabs(["Cabling", "Ports by switch", "vPC pairs", "VRF-lite"])
with tab_links:
    kinds = sorted({r["type"] for r in plan.links})
    show = st.multiselect("Show", kinds, default=kinds, key="cable_kinds")
    st.dataframe(pd.DataFrame([r for r in plan.links if r["type"] in show], columns=LINK_COLUMNS),
                 width="stretch", hide_index=True)
with tab_ports:
    sw = st.selectbox("Switch", ["All switches", *sorted({r["switch"] for r in plan.ports})], key="cable_switch")
    rows = plan.ports if sw == "All switches" else [r for r in plan.ports if r["switch"] == sw]
    st.dataframe(pd.DataFrame(rows, columns=PORT_COLUMNS), width="stretch", hide_index=True)
with tab_vpc:
    st.dataframe(pd.DataFrame(plan.vpc), width="stretch", hide_index=True)
with tab_lite:
    if plan.vrf_lite:
        st.dataframe(pd.DataFrame(plan.vrf_lite), width="stretch", hide_index=True)
    else:
        st.caption("No VRF-lite handoffs.")
