"""Day-2 tasks, project history and undo/redo."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from nacbuilder.checks import check_project
from nacbuilder.diffing import compare_projects
from nacbuilder.history import EMPTY, History, UndoStack
from nacbuilder.models import Project
from nacbuilder.sample import standard_example
from nacbuilder.tasks import (
    HostPorts,
    NetworkSpec,
    VrfLiteSpec,
    border_switches,
    decommission,
    new_tenant,
    next_leaf_names,
    next_mgmt_ips,
    onboard_leaf_pair,
)

ROOT = Path(__file__).resolve().parent.parent


def errors(p):
    return [i.message for i in check_project(p) if i.level == "error"]


# --- tasks ------------------------------------------------------------------------------
def test_new_tenant_with_vrf_lite():
    p = standard_example()
    q = new_tenant(p, "PROD", [NetworkSpec("WEB", "10.20.1.1/24"), NetworkSpec("APP", "10.20.2.1/24", vlan_id=2399)],
                   vrf_lite=VrfLiteSpec(border_switches(p), ["Ethernet1/49"], "10.254.0.0/24", 30, 65500))
    assert check_project(q) == []
    assert p == standard_example(), "the input project must not be modified"
    vrf = q.vrfs[-1]
    assert (vrf.name, vrf.vrf_id, vrf.vlan_id) == ("PROD", 50002, 2001)
    assert [(n.name, n.net_id, n.vlan_id, n.vrf_name) for n in q.networks[-2:]] == [
        ("WEB", 30002, 2301, "PROD"), ("APP", 30003, 2399, "PROD")]
    # "all" is shared with other networks, so PROD got its own group with the external borders added
    assert vrf.vrf_attach_group == "PROD-vrf"
    assert {a.hostname for a in q.attachments if a.group == "PROD-vrf"} >= {"dc1-border-external1", "dc1-border-external2"}
    assert [l.name for l in q.vrf_lites] == ["PROD-vrf-lite"]
    d = compare_projects(p, q)
    assert "VRF PROD" in d.added and "network WEB" in d.added and "VRF-lite PROD-vrf-lite" in d.added


def test_new_tenant_creates_missing_group_and_rejects_duplicates():
    p = standard_example()
    q = new_tenant(p, "DEV", [NetworkSpec("DEV-WEB")], attach_group="dev-leafs")
    assert {a.hostname for a in q.attachments if a.group == "dev-leafs"} == {f"dc1-leaf{i}" for i in range(1, 5)}
    assert check_project(q) == []
    with pytest.raises(ValueError, match="already exists"):
        new_tenant(q, "DEV", [])
    with pytest.raises(ValueError, match="already used"):
        new_tenant(q, "QA", [NetworkSpec("DEV-WEB")])


def test_onboard_leaf_pair():
    p = standard_example()
    names = next_leaf_names(p)
    ips, mask, gw = next_mgmt_ips(p)
    assert names == ("dc1-leaf5", "dc1-leaf6")
    assert (ips, mask, gw) == (["10.10.0.25", "10.10.0.26"], 24, "10.10.0.1")
    q = onboard_leaf_pair(p, names, ("FDO1", "FDO2"), tuple(ips), mask, gw, ["Ethernet1/53", "Ethernet1/54"],
                          host_ports=HostPorts("Ethernet1/1-2", "access", access_vlan=2300), groups=["all"])
    assert check_project(q) == []
    pair = q.vpc_peers[-1]
    assert (pair.peer1, pair.peer2, pair.domain_id) == ("dc1-leaf5", "dc1-leaf6", 6)
    pcs = [(i.switch, i.name, i.vpc_id, i.members, i.access_vlan) for i in q.interfaces]
    assert pcs == [
        ("dc1-leaf5", "port-channel11", 11, ["Ethernet1/1"], 2300), ("dc1-leaf6", "port-channel11", 11, ["Ethernet1/1"], 2300),
        ("dc1-leaf5", "port-channel12", 12, ["Ethernet1/2"], 2300), ("dc1-leaf6", "port-channel12", 12, ["Ethernet1/2"], 2300),
    ]
    assert {"dc1-leaf5", "dc1-leaf6"} <= {a.hostname for a in q.attachments if a.group == "all"}
    with pytest.raises(ValueError, match="already exist"):
        onboard_leaf_pair(q, ("dc1-leaf5", "dc1-leaf7"))
    with pytest.raises(ValueError, match="peer-link port"):
        onboard_leaf_pair(p, ("x1", "x2"), peerlink_ports=["Ethernet1/53"], host_ports=HostPorts("Ethernet1/53"))


def test_decommission_switch_pair_and_vrf():
    p = standard_example()
    p = new_tenant(p, "PROD", [NetworkSpec("WEB", "10.20.1.1/24")],
                   vrf_lite=VrfLiteSpec(border_switches(p), ["Ethernet1/49"], "10.254.0.0/24", 30, 65500))
    p = onboard_leaf_pair(p, ("dc1-leaf5", "dc1-leaf6"), peerlink_ports=["Ethernet1/53"], host_ports=HostPorts("Ethernet1/1"),
                          groups=["all"])
    q = decommission(p, switches=["dc1-leaf5"], vrfs=["PROD"])  # peer leaf6 goes too
    assert check_project(q) == []
    names = {s.name for s in q.switches}
    assert "dc1-leaf5" not in names and "dc1-leaf6" not in names
    assert not any(i.switch in ("dc1-leaf5", "dc1-leaf6") for i in q.interfaces)
    assert not any(v.name == "PROD" for v in q.vrfs) and not any(n.name == "WEB" for n in q.networks)
    assert q.vrf_lites == [] and not any(i.mode == "routed_sub" for i in q.interfaces)
    assert "PROD-vrf" not in q.attach_groups(), "the group only PROD used is removed"
    assert "all" in q.attach_groups()


def test_decommission_one_peer_only_drops_vpc_ids():
    p = onboard_leaf_pair(standard_example(), ("dc1-leaf5", "dc1-leaf6"), peerlink_ports=["Ethernet1/53"],
                          host_ports=HostPorts("Ethernet1/1"))
    q = decommission(p, switches=["dc1-leaf5"], include_vpc_peer=False)
    left = [i for i in q.interfaces if i.switch == "dc1-leaf6"]
    assert left and all(i.vpc_id is None for i in left)
    assert not any("vPC" in m for m in errors(q))
    with pytest.raises(ValueError, match="unknown switch"):
        decommission(q, switches=["nope"])


# --- history -------------------------------------------------------------------------------
def test_history_records_lists_loads_and_prunes(tmp_path):
    h = History(tmp_path, keep=3)
    p = standard_example()
    snaps = [h.record(p.model_copy(update={"vrfs": p.vrfs[:0]}) if i % 2 else p, f"change {i}") for i in range(5)]
    listed = h.list("dc1")
    assert [s.label for s in listed] == ["change 4", "change 3", "change 2"]
    assert listed[0].counts["switches"] == 14
    assert History.load(snaps[-1].path) == p
    assert History.load(EMPTY) == Project()
    assert h.fabrics() == ["dc1"]
    assert h.clear("dc1") == 3 and h.list("dc1") == []


def test_undo_stack():
    s = UndoStack()
    assert not s.can_undo and not s.can_redo
    for i in range(3):
        s.push(f"e{i}", f"l{i}")
    assert s.undo() == ("e1", "l2") and s.undo() == ("e0", "l1")
    assert not s.can_undo and s.redo() == ("e1", "l1")
    s.push("e9", "l9")  # a new change drops the redo branch
    assert s.entries == ["e0", "e1", "e9"] and not s.can_redo


def test_app_undo_redo_and_history_files(tmp_path, monkeypatch):
    monkeypatch.setenv("NACB_HISTORY_DIR", str(tmp_path / "h"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    undo_btn = next(b for b in at.sidebar.button if b.label == "Undo")
    assert undo_btn.disabled
    next(b for b in at.sidebar.button if b.label == "Load example").click().run()
    assert len(at.session_state["project"].switches) == 14
    assert [s.label for s in History(tmp_path / "h").list("dc1")] == ["Loaded the example fabric"]
    next(b for b in at.sidebar.button if b.label == "Undo").click().run()
    assert at.session_state["project"] == Project()
    next(b for b in at.sidebar.button if b.label == "Redo").click().run()
    assert len(at.session_state["project"].switches) == 14
    assert not at.exception


def test_tasks_page_preview_and_apply():
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    at.run()
    assert not at.exception and at.title
    decom = at.tabs[2]
    decom.multiselect[0].set_value(["dc1-leaf3"])
    next(b for b in decom.button if b.label == "Preview").click().run()
    assert not at.exception
    assert at.session_state["task_preview"]["label"] == "Decommission dc1-leaf3"
    assert any("switch dc1-leaf4" in m.value for m in at.markdown)  # the vPC peer goes too
    next(b for b in at.button if b.label == "Apply").click().run()
    names = {s.name for s in at.session_state["project"].switches}
    assert "dc1-leaf3" not in names and "dc1-leaf4" not in names
    assert "task_preview" not in at.session_state


def test_history_page_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("NACB_HISTORY_DIR", str(tmp_path / "h"))
    p = standard_example()
    History().record(p, "first")
    at = AppTest.from_file(str(ROOT / "views" / "history.py"), default_timeout=30)
    at.session_state["project"] = p.model_copy(update={"switches": p.switches[:4]})
    at.run()
    assert not at.exception and at.title
