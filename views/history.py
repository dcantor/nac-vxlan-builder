import streamlit as st

from nacbuilder.diffing import compare_projects
from nacbuilder.history import History
from nacbuilder.store import Store
from nacbuilder.ui import current_id, project, set_project

p = project()
hist = History()

st.title("History")
st.caption(
    f"A snapshot is saved every time the project changes, in `{hist.root}`. Restoring one is itself a change, "
    "so you can always come back. **Undo** and **Redo** in the sidebar step through this session's changes."
)
if err := st.session_state.get("history_error"):
    st.warning(f"The last snapshot couldn't be saved: {err}", icon="⚠️")

fabrics = hist.fabrics()
if not fabrics:
    st.info("No snapshots yet. They appear as soon as you save a change.", icon=":material/info:")
    st.stop()
# History folders are named after the fabric's ID (older versions used its name)
names = {r.id: r.name for r in Store().list()}
cur = current_id()
default = fabrics.index(cur) if cur in fabrics else (fabrics.index(p.fabric.name) if p.fabric.name in fabrics else 0)
fabric = st.selectbox("Fabric", fabrics, index=default,
                      format_func=lambda f: names.get(f, f"{f} (older history)") + (" (open)" if f == cur else ""))
snaps = hist.list(fabric)
st.caption(f"{len(snaps)} snapshot(s), newest first (the last {hist.keep} are kept).")

rows = [{
    "time": s.created.strftime("%Y-%m-%d %H:%M:%S"),
    "change": s.label,
    "switches": s.counts.get("switches"),
    "vPC": s.counts.get("vpc"),
    "interfaces": s.counts.get("interfaces"),
    "VRFs": s.counts.get("vrfs"),
    "networks": s.counts.get("networks"),
} for s in snaps]
event = st.dataframe(rows, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row",
                     key=f"hist_{fabric}")
picked = event.selection.rows[0] if event and event.selection.rows else None

if picked is None:
    st.caption("Select a snapshot to compare it with the current project or restore it.")
else:
    snap = snaps[picked]
    st.subheader(f"{snap.created:%Y-%m-%d %H:%M:%S}: {snap.label}", divider="gray")
    try:
        old = History.load(snap.path)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    diff = compare_projects(p, old)
    if diff.empty:
        st.success("Same switches, vPC, interfaces, VRFs, networks, groups and VRF-lite as the current project.", icon="✅")
    else:
        st.caption("Restoring this snapshot would:")
        c1, c2, c3 = st.columns(3)
        for col, title, items, icon in ((c1, "Add back", diff.added, "🟢"), (c2, "Remove", diff.removed, "🔴"),
                                       (c3, "Change", diff.changed, "🟡")):
            col.markdown(f"{icon} **{title} ({len(items)})**")
            if items:
                col.markdown("\n".join(f"- {i}" for i in items[:40]) + (f"\n- … {len(items) - 40} more" if len(items) > 40 else ""))
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("Restore this snapshot", type="primary", width="stretch"):
        set_project(old, f"Restored snapshot from {snap.created:%H:%M:%S} ({snap.label})")
        st.rerun()
    c2.download_button("Download as project", old.model_dump_json(indent=2), file_name=f"{names.get(fabric, fabric)}-{snap.id}.nacproj.json",
                       mime="application/json", width="stretch")

with st.expander("Delete history", icon=":material/delete:"):
    st.caption(f"Deletes all {len(snaps)} snapshot(s) for `{names.get(fabric, fabric)}` from disk. This can't be undone.")
    if st.button(f"Delete {len(snaps)} snapshot(s) for {names.get(fabric, fabric)}"):
        n = hist.clear(fabric)
        st.toast(f"Deleted {n} snapshot(s)")
        st.rerun()
