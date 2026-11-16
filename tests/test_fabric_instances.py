"""Fabric page: list fabric instances, tick some, delete them after typing "Yes"."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nacbuilder import paths, workspace
from nacbuilder.clone import CloneSpec, clone_fabric
from nacbuilder.history import History
from nacbuilder.store import Store
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


IDS = {"dc1": "id-dc1", "dc2": "id-dc2", "dc3": "id-dc3"}


def seed():
    s, h = Store(), History()
    dc1 = full_fabric()
    for name in ("dc2", "dc3"):
        q = clone_fabric(dc1, CloneSpec(name, "dc1-", f"{name}-"))
        s.save(IDS[name], q)
        h.record(q, "seed", IDS[name])
        paths.fabric_export_dir(name)
    s.save(IDS["dc1"], dc1)
    return dc1


def boxes(at):
    return {c.label.split(" · ")[0]: c for c in at.checkbox if c.key and "fab_del_" in c.key}


def page(p):
    at = AppTest.from_file(str(ROOT / "views" / "fabric.py"), default_timeout=30)
    at.session_state["project"] = p
    at.session_state["fabric_id"] = IDS["dc1"]
    return at.run()


def test_delete_fabric_removes_store_history_and_export():
    seed()
    assert workspace.delete_fabric(IDS["dc2"]) == ["the fabric", "1 history snapshot(s)", "export/dc2/"]
    assert [e.name for e in workspace.fabrics()] == ["dc1", "dc3"]
    assert not (paths.export_root() / "dc2").exists() and (paths.export_root() / "dc3").is_dir()


def test_export_folder_stays_while_a_same_name_fabric_exists():
    seed()
    Store().save("id-dc3b", Store().load(IDS["dc3"]))
    assert workspace.delete_fabric(IDS["dc3"]) == ["the fabric", "1 history snapshot(s)"]
    assert (paths.export_root() / "dc3").is_dir()


def test_lists_fabrics_with_checkboxes():
    at = page(seed())
    assert not at.exception
    b = boxes(at)
    assert set(b) == {"dc1", "dc2", "dc3"} and "open now" in b["dc1"].label
    assert next(x for x in at.button if x.key == "fab_delete_btn").disabled  # nothing ticked


def test_delete_needs_yes():
    at = page(seed())
    boxes(at)["dc2"].check()
    boxes(at)["dc3"].check()
    at.run()
    at.button(key="fab_delete_btn").click().run()
    assert sorted(at.session_state["fab_delete"]) == ["id-dc2", "id-dc3"]
    assert any("Delete 2 fabric(s)" in e.value for e in at.error)
    assert at.button(key="fab_delete_go").disabled
    at.text_input(key="fab_delete_confirm").set_value("yes").run()
    assert at.button(key="fab_delete_go").disabled  # must be exactly "Yes"
    at.text_input(key="fab_delete_confirm").set_value("Yes").run()
    at.button(key="fab_delete_go").click().run()
    assert not at.exception
    assert [e.name for e in workspace.fabrics()] == ["dc1"]
    assert at.session_state["project"].fabric.name == "dc1" and at.session_state["flash"] == "Deleted 2 fabric(s): dc2, dc3"
    assert set(boxes(at)) == {"dc1"}


def test_cancel_keeps_everything():
    at = page(seed())
    boxes(at)["dc2"].check().run()
    at.button(key="fab_delete_btn").click().run()
    at.button(key="fab_delete_cancel").click().run()
    assert "fab_delete" not in at.session_state and len(workspace.fabrics()) == 3


def test_deleting_the_open_fabric_opens_an_empty_one():
    at = page(seed())
    boxes(at)["dc1"].check().run()
    at.button(key="fab_delete_btn").click().run()
    assert any("The open fabric is one of them" in e.value for e in at.error)
    at.text_input(key="fab_delete_confirm").set_value("Yes").run()
    at.button(key="fab_delete_go").click().run()
    q = at.session_state["project"]
    assert q.switches == [] and "dc1" not in {e.name for e in workspace.fabrics()}
    assert at.session_state["fabric_id"] != IDS["dc1"]
