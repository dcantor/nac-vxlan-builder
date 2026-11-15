"""Exports go to export/<fabric>/ in the project root; the app creates a sub folder per fabric."""

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import paths
from nacbuilder.generate import apply_write, render_all
from nacbuilder.sample import standard_example

ROOT = Path(__file__).resolve().parent.parent


def test_default_root_is_the_project_export_folder(monkeypatch):
    monkeypatch.delenv("NACB_EXPORT_DIR")
    assert paths.export_root() == ROOT / "export"
    assert paths.fabric_export_dir("dc1", create=False) == ROOT / "export" / "dc1"


def test_fabric_folder_is_created():
    d = paths.fabric_export_dir("dc1")
    assert d == Path(os.environ["NACB_EXPORT_DIR"]) / "dc1" and d.is_dir()


def test_app_creates_a_folder_per_fabric():
    root = paths.export_root()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    p = standard_example()
    at.session_state["project"] = p
    at.run()
    assert not at.exception
    assert (root / p.fabric.name).is_dir()
    other = p.model_copy(update={"fabric": p.fabric.model_copy(update={"name": "dmz1"})})
    at.session_state["project"] = other
    at.run()
    assert sorted(x.name for x in root.iterdir()) == sorted({p.fabric.name, "dmz1"})


def test_review_page_writes_to_the_fabric_export_folder():
    p = standard_example()
    at = AppTest.from_file(str(ROOT / "views" / "review.py"), default_timeout=60)
    at.session_state["project"] = p
    at.run()
    assert not at.exception
    dest = next(t for t in at.text_input if t.label == "Fabric folder")
    assert dest.value == str(paths.export_root() / p.fabric.name)
    written, _ = apply_write(p, Path(dest.value), remove_stale=False)
    assert sorted(written) == sorted(render_all(p))
