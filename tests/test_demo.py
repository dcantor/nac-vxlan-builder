"""Demo mode (Design standards → Demo mode): load a simulated fabric, export it, delete it."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import paths
from nacbuilder.checks import check_project
from nacbuilder.demo import DEMO_NAME, build_demo, delete_demo, demo_export_dir, is_demo
from nacbuilder.generate import apply_write, render_all
from nacbuilder.history import History
from nacbuilder.portmap import DISABLED, switch_ports
from nacbuilder.store import Store
from nacbuilder.validate import nac_validate
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


def test_demo_fabric_shows_the_features():
    p = build_demo()
    assert is_demo(p) and p.fabric.name == DEMO_NAME
    assert check_project(p) == []
    assert nac_validate(p).ok
    assert p.leaf_roles == ["compute", "storage"] and all(s.model and s.serial_number for s in p.switches)
    assert len(p.vpc_peers) == 6 and {v.name for v in p.vrfs} == {"PROD", "DEV"} and len(p.networks) == 5
    assert p.vrf_lites and any(i.vpc_id for i in p.interfaces)
    assert any(pt.state == DISABLED for pt in switch_ports(p, "demo-leaf-compute3"))  # red on the port map


def test_delete_removes_export_and_history():
    p = build_demo()
    apply_write(p, paths.fabric_export_dir(DEMO_NAME), remove_stale=False)
    History().record(p, "demo")
    other = paths.fabric_export_dir("dc1")
    removed = delete_demo()
    assert removed == [f"export/{DEMO_NAME}/", "1 history snapshot(s)"]
    assert not demo_export_dir().exists() and other.is_dir()
    assert delete_demo() == []


def page(project):
    at = AppTest.from_file(str(ROOT / "views" / "standards_editor.py"), default_timeout=60)
    at.session_state["project"] = project
    return at.run()


def test_load_export_delete_restores_previous_fabric():
    before = full_fabric()
    at = page(before)
    assert not at.exception
    assert any("`dc1` stays in your fabric list" in i.value for i in at.info)
    before_id = at.session_state["fabric_id"] = "dc1fabric001"
    Store().save(before_id, before)
    at.button(key="demo_load").click().run()
    assert is_demo(at.session_state["project"]) and at.session_state["pre_demo"] == before_id
    assert at.session_state["fabric_id"] != before_id  # the demo is its own fabric
    assert Store().load(before_id) == before
    next(b for b in at.button if b.label == f"Write to export/{DEMO_NAME}/").click().run()
    assert sorted(x.name for x in demo_export_dir().iterdir()) == sorted(render_all(at.session_state["project"]))
    assert at.get("download_button")  # zip download offered
    at.button(key="demo_delete").click().run()
    assert not at.exception
    assert at.session_state["project"] == before and "pre_demo" not in at.session_state
    assert at.session_state["fabric_id"] == before_id
    assert [r.name for r in Store().list()] == ["dc1"]  # the demo fabric is gone from the store
    assert not demo_export_dir().exists()
    assert at.session_state["flash"].startswith("Deleted the demo (export/demo-dc1/")


def test_delete_without_previous_fabric_gives_a_new_one():
    at = page(build_demo())
    at.button(key="demo_delete").click().run()
    q = at.session_state["project"]
    assert not is_demo(q) and q.switches == []


def test_sidebar_badge():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["project"] = build_demo()
    at.run()
    assert not at.exception
    assert any("Demo mode:" in w.value for w in at.sidebar.warning)
