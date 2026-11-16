"""Frozen header: shows the open fabric and switches to another one (from History)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import workspace
from nacbuilder.clone import CloneSpec, clone_fabric
from nacbuilder.demo import build_demo
from nacbuilder.history import History
from nacbuilder.store import Store
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


def test_store_lists_fabrics_by_id():
    s = Store()
    dc1 = full_fabric()
    s.save("a1", dc1)
    s.save("b2", clone_fabric(dc1, CloneSpec("dc2", "dc1-", "dc2-")))
    assert [r.id for r in workspace.fabrics()] == ["b2", "a1"]  # most recently changed first
    assert s.load("a1") == dc1
    assert workspace.describe(s.record("a1")).startswith("dc1 · 14 switches, 1 VRFs · changed")


def test_rename_keeps_the_fabric():
    s = Store()
    dc1 = full_fabric()
    s.save("a1", dc1)
    s.save("a1", dc1.model_copy(update={"fabric": dc1.fabric.model_copy(update={"name": "dc1-new"})}))
    assert [(r.id, r.name) for r in s.list()] == [("a1", "dc1-new")]


def test_same_name_fabrics_are_separate():
    s = Store()
    s.save("a1", full_fabric())
    s.save("b2", full_fabric().model_copy(update={"vrfs": []}))
    recs = s.list()
    assert [r.name for r in recs] == ["dc1", "dc1"]
    labels = [workspace.describe(r, recs) for r in recs]
    assert labels[0].startswith("dc1 [b2] · 14 switches") and labels[1].startswith("dc1 [a1] · 14 switches, 1 VRFs")


def test_migrates_old_name_history_once():
    h = History()
    h.record(full_fabric(), "old")  # older versions kept History by fabric name
    recs = workspace.fabrics()
    assert [r.name for r in recs] == ["dc1"]
    assert [x.label for x in h.list(recs[0].id)] == ["old"]  # its History moved to the ID folder
    assert workspace.fabrics() == recs  # only once


def run_app(p, fid=None):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["project"] = p
    if fid:
        at.session_state["fabric_id"] = fid
    return at.run()


def test_header_shows_fabric_and_switches():
    Store().save("demo01", build_demo())
    Store().save("dc1a", full_fabric())
    at = run_app(full_fabric(), "dc1a")
    assert not at.exception
    assert any("Editing fabric **`dc1`**" in m.value for m in at.markdown)
    sel = next(s for s in at.selectbox if s.label == "Switch fabric")
    assert sel.options[0] == "dc1 (open)" and any(o.startswith("demo-dc1 · 16 switches") for o in sel.options)
    sel.set_value("demo01").run()
    assert not at.exception
    q = at.session_state["project"]
    assert q.fabric.name == "demo-dc1" and len(q.switches) == 16 and at.session_state["fabric_id"] == "demo01"
    assert "undo" not in at.session_state or not at.session_state["undo"].can_undo
    assert any("Demo" in m.value and "demo-dc1" in m.value for m in at.markdown)


def test_every_change_is_saved_and_new_sessions_reopen_it():
    at = run_app(full_fabric(), "dc1a")
    next(b for b in at.sidebar.button if b.label == "Load example").click().run()  # a new fabric, not dc1a
    new_id = at.session_state["fabric_id"]
    assert new_id != "dc1a" and Store().exists(new_id)
    fresh = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()  # a new browser session
    assert fresh.session_state["fabric_id"] == new_id and len(fresh.session_state["project"].switches) == 14


def test_switcher_disabled_with_one_fabric():
    at = run_app(full_fabric())
    sel = next(s for s in at.selectbox if s.label == "Switch fabric")
    assert sel.disabled and sel.options == ["dc1 (open)"]


def test_header_shows_nac_version(monkeypatch):
    from nacbuilder import ui

    monkeypatch.setattr(ui, "_installed_nac", lambda: None)
    assert ui.nac_version_text().startswith(":material/sell: NaC `cisco.nac_dc_vxlan` 0.9.1 · ND 4.2 · builder 0.1.0")
    monkeypatch.setattr(ui, "_installed_nac", lambda: "0.9.1")
    assert ui.nac_version_text().endswith("installed ✓")
    monkeypatch.setattr(ui, "_installed_nac", lambda: "0.10.0")
    assert ui.nac_version_text().endswith(":orange[installed collection is 0.10.0]")
    at = run_app(full_fabric())
    assert any("NaC `cisco.nac_dc_vxlan` 0.9.1" in m.value for m in at.markdown)


def test_theme_toggle_in_header():
    from nacbuilder.ui import page_paths

    paths = page_paths()
    assert paths[0] == "/" and "/switches" in paths and "/tasks" in paths
    at = run_app(full_fabric())
    frames = [e for e in at.get("iframe")]
    html = next(f.proto.srcdoc for f in frames if "stActiveTheme-" in f.proto.srcdoc)
    assert '"/switches"' in html and "window.parent.location.reload()" in html
    assert "Switch to dark mode" in html or "Switch to light mode" in html


def test_header_follows_a_rename_straight_away():
    at = run_app(full_fabric(), "dc1a")
    next(t for t in at.text_input if t.label == "Fabric name").set_value("dc9")
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception
    assert any("Editing fabric **`dc9`**" in m.value for m in at.markdown)
    assert [(r.id, r.name) for r in Store().list()] == [("dc1a", "dc9")]  # same fabric, new name
