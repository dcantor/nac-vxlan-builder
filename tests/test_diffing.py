import shutil
from pathlib import Path

from nacbuilder.diffing import change_summary, file_diffs
from nacbuilder.generate import apply_write
from nacbuilder.importer import import_folder
from nacbuilder.models import Switch
from nacbuilder.sample import standard_example

GOLDEN = Path(__file__).parent / "golden"


def test_new_folder_is_all_new_files(tmp_path):
    p = standard_example()
    diffs = file_diffs(p, tmp_path / "dc1")
    assert {d.status for d in diffs} == {"new"}
    assert change_summary(p, tmp_path / "dc1") is None


def test_unchanged_after_write(tmp_path):
    p = standard_example()
    apply_write(p, tmp_path, remove_stale=False)
    assert {d.status for d in file_diffs(p, tmp_path)} == {"unchanged"}
    assert change_summary(p, tmp_path).empty


def test_edits_show_up_as_item_changes(tmp_path):
    shutil.copytree(GOLDEN, tmp_path / "f")
    p = import_folder(tmp_path / "f").project
    p.switches = [s for s in p.switches if s.name != "netascode-leaf4"]
    p.switches.append(Switch(name="netascode-leaf5", role="leaf"))
    p.vrfs[0].vlan_id = 2050
    s = change_summary(p, tmp_path / "f")
    assert s.added == ["switch netascode-leaf5"]
    assert s.removed == ["switch netascode-leaf4"]
    assert "VRF NaC-VRF01" in s.changed
    topo = next(d for d in file_diffs(p, tmp_path / "f") if d.name == "topology_switches.nac.yaml")
    assert topo.status == "changed" and "+      - name: netascode-leaf5" in topo.diff
    assert "-      - name: netascode-leaf4" in topo.diff


def test_superseded_files_show_as_removed(tmp_path):
    p = standard_example()
    apply_write(p, tmp_path, remove_stale=False)
    p.networks = []
    diffs = {d.name: d for d in file_diffs(p, tmp_path, remove_stale=True)}
    assert diffs["networks.nac.yaml"].status == "removed" and diffs["networks.nac.yaml"].removed > 0
    assert "networks.nac.yaml" not in {d.name for d in file_diffs(p, tmp_path, remove_stale=False)}
