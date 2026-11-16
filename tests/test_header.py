"""Frozen header: shows the open fabric and switches to another one (from History)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import workspace
from nacbuilder.clone import CloneSpec, clone_fabric
from nacbuilder.demo import build_demo
from nacbuilder.history import History
from nacbuilder.models import Project
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


def test_workspace_lists_latest_state_per_fabric():
    h = History()
    dc1 = full_fabric()
    h.record(dc1, "first")
    dc1b = dc1.model_copy(update={"vrfs": []})
    h.record(dc1b, "second")
    h.record(clone_fabric(dc1, CloneSpec("dc2", "dc1-", "dc2-")), "clone")
    entries = workspace.fabrics()
    assert [e.name for e in entries] == ["dc2", "dc1"]  # most recently changed first
    assert workspace.latest("dc1") == dc1b and workspace.latest("nope") is None
    assert workspace.describe(entries[1]).startswith("dc1 · 14 switches · changed")


def test_save_current_only_when_changed():
    p = full_fabric()
    assert workspace.save_current(p) is True
    assert workspace.save_current(p) is False
    assert workspace.save_current(Project()) is False


def run_app(p):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["project"] = p
    return at.run()


def test_header_shows_fabric_and_switches():
    History().record(build_demo(), "demo")
    at = run_app(full_fabric())
    assert not at.exception
    assert any("Editing fabric **`dc1`**" in m.value for m in at.markdown)
    sel = next(s for s in at.selectbox if s.label == "Switch fabric")
    assert sel.options[0] == "dc1 (open)" and any(o.startswith("demo-dc1 · 16 switches") for o in sel.options)
    sel.set_value("demo-dc1").run()
    assert not at.exception
    q = at.session_state["project"]
    assert q.fabric.name == "demo-dc1" and len(q.switches) == 16
    assert workspace.latest("dc1") == full_fabric()  # the open fabric was saved before switching
    assert "undo" not in at.session_state or not at.session_state["undo"].can_undo
    assert any("Demo" in m.value and "demo-dc1" in m.value for m in at.markdown)


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
