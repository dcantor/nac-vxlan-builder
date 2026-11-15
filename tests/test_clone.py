"""Clone fabric (Review & export): copy under a new name with switches renamed everywhere."""

from ipaddress import IPv4Address
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from nacbuilder import paths
from nacbuilder.checks import check_project
from nacbuilder.clone import CloneSpec, clone_fabric, common_prefix, suggest
from nacbuilder.generate import render_all
from nacbuilder.models import Project
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


def test_suggestion():
    p = full_fabric()
    assert common_prefix(p) == "dc1-"
    s = suggest(p)
    assert (s.name, s.old_prefix, s.new_prefix) == ("dc2", "dc1-", "dc2-")
    p.fabric = p.fabric.model_copy(update={"name": "prod"})
    assert suggest(p).name == "prod-copy"


def test_clone_renames_everywhere_and_leaves_original():
    p = full_fabric()
    before = p.model_copy(deep=True)
    q = clone_fabric(p, CloneSpec("dc2", "dc1-", "dc2-", first_mgmt_ip="10.20.0.11", bgp_asn="65002"))
    assert p == before
    assert q.fabric.name == "dc2" and q.ibgp.bgp_asn == "65002"
    names = {s.name for s in q.switches}
    assert all(n.startswith("dc2-") for n in names)
    assert {i.switch for i in q.interfaces} <= names
    assert {x for v in q.vpc_peers for x in (v.peer1, v.peer2)} <= names
    assert {a.hostname for a in q.attachments} <= names
    assert {s.name for lite in q.vrf_lites for s in lite.switches} <= names
    assert all(s.serial_number is None for s in q.switches)
    old_ips = sorted(s.management.management_ipv4_address for s in p.switches)
    new_ips = sorted(s.management.management_ipv4_address for s in q.switches)
    delta = int(IPv4Address("10.20.0.11")) - int(old_ips[0])
    assert [int(b) - int(a) for a, b in zip(old_ips, new_ips)] == [delta] * len(old_ips)
    assert [i.message for i in check_project(q) if i.level == "error"] == []
    assert "dc1-" not in "".join(render_all(q).values())


def test_clone_keeps_preserved_settings_under_new_names():
    p = full_fabric()
    p.preserved.source, p.preserved.files = "/repo/host_vars/dc1", ["topology.nac.yaml"]
    p.preserved.switches = {"dc1-leaf1": {"poap": {"bootstrap": True}}}
    p.preserved.interfaces = {"dc1-leaf1/Ethernet1/1": {"speed": "auto"}}
    p.preserved.attach = {"vrf/all/dc1-leaf1": {"x": 1}}
    p.preserved.vpc_peers = {"dc1-leaf1|dc1-leaf2": {"y": 2}}
    q = clone_fabric(p, CloneSpec("dc2", "dc1-", "dc2-"))
    pv = q.preserved
    assert pv.source is None and pv.files == []
    assert list(pv.switches) == ["dc2-leaf1"] and list(pv.interfaces) == ["dc2-leaf1/Ethernet1/1"]
    assert list(pv.attach) == ["vrf/all/dc2-leaf1"] and list(pv.vpc_peers) == ["dc2-leaf1|dc2-leaf2"]


def test_clone_errors():
    p = full_fabric()
    with pytest.raises(ValueError, match="different fabric name"):
        clone_fabric(p, CloneSpec("dc1"))
    with pytest.raises(ValueError):
        clone_fabric(p, CloneSpec("2bad"))
    with pytest.raises(ValueError, match="No switch names start"):
        clone_fabric(p, CloneSpec("dc2", "zz-", "dc2-"))
    with pytest.raises(ValueError, match="no management IPs"):
        clone_fabric(Project(), CloneSpec("x2", first_mgmt_ip="10.0.0.1"))
    q = clone_fabric(p, CloneSpec("dc2", clear_serials=False))  # keep names and serials
    assert [s.name for s in q.switches] == [s.name for s in p.switches]
    assert [s.serial_number for s in q.switches] == [s.serial_number for s in p.switches]


def test_clone_from_review_page():
    at = AppTest.from_file(str(ROOT / "views" / "review.py"), default_timeout=60)
    at.session_state["project"] = full_fabric()
    at.run()
    assert not at.exception
    next(b for b in at.button if b.label == "Clone fabric").click().run()
    assert not at.exception
    q = at.session_state["project"]
    assert q.fabric.name == "dc2" and q.switches[0].name.startswith("dc2-")
    out = paths.export_root() / "dc2"
    assert sorted(x.name for x in out.iterdir()) == sorted(render_all(q))
    assert "Cloned dc1 to dc2 and wrote" in at.session_state["flash"]
