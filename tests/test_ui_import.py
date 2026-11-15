"""Run the real page scripts with Streamlit's AppTest and a stub file uploader."""

import io
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from nacbuilder.sample import standard_example

ROOT = Path(__file__).resolve().parent.parent


class Upload(io.BytesIO):
    def __init__(self, name: str, data: str):
        super().__init__(data.encode())
        self.name = name


@pytest.fixture
def uploads(monkeypatch):
    """Map uploader key prefix -> CSV text; served once (before the post-save editor_ver bump)."""
    files: dict[str, str] = {}

    def fake_uploader(label, *args, key=None, **kwargs):
        for prefix, text in files.items():
            if key == f"{prefix}_0":
                return Upload(f"{prefix}.csv", text)
        return None

    monkeypatch.setattr(st, "file_uploader", fake_uploader)
    return files


def run_page(page: str, project=None) -> AppTest:
    at = AppTest.from_file(str(ROOT / "views" / page), default_timeout=30)
    if project is not None:
        at.session_state["project"] = project
    return at.run()


def test_vrf_csv_replaces_table(uploads):
    uploads["vrfs_csv"] = "Name,VRF_ID,VLAN_ID,vrf_attach_group\nPROD,50101,2100,all\nDEV,50102,2101,all\n"
    at = run_page("vrfs.py", standard_example())
    assert not at.exception
    assert [v.name for v in at.session_state["project"].vrfs] == ["PROD", "DEV"]


def test_network_csv_appends(uploads):
    uploads["networks_csv"] = "name,vrf_name,net_id,vlan_id,gw_ip_address\nWEB,VRF01,30101,2400,10.20.0.1/24\n"
    at = AppTest.from_file(str(ROOT / "views" / "networks.py"), default_timeout=30)
    at.session_state["project"] = standard_example()
    at.session_state["networks_csv_mode"] = "Append to the table"
    at.run()
    assert not at.exception
    assert [n.name for n in at.session_state["project"].networks] == ["NET01", "WEB"]


def test_bad_csv_imports_nothing_and_shows_errors(uploads):
    uploads["switches_csv"] = "name,role\nsw1,leaf\nsw2,router\n"
    p = standard_example()
    at = run_page("switches.py", p)
    assert not at.exception
    assert at.session_state["project"].switches == p.switches
    assert any("Line 3" in e.value and "role" in e.value for e in at.error)


def test_import_page_reads_folder_and_loads(tmp_path):
    import shutil

    fabric = tmp_path / "host_vars" / "nac-fabric1"
    shutil.copytree(ROOT / "tests" / "golden", fabric)
    at = AppTest.from_file(str(ROOT / "views" / "import_yaml.py"), default_timeout=30)
    at.session_state["import_root"] = str(tmp_path)
    at.run()
    assert not at.exception
    assert at.selectbox[0].value == fabric
    next(b for b in at.button if b.label == "Read folder").click().run()
    assert not at.exception
    assert [m.value for m in at.metric][:4] == ["nac-fabric1", "6", "3", "3"]
    load = next(b for b in at.button if b.label.startswith("Load into the app"))
    load.click().run()
    p = at.session_state["project"]
    assert p.fabric.name == "nac-fabric1" and len(p.switches) == 6
    assert p.preserved.source == str(fabric)


PAGES = ["fabric.py", "switches.py", "vpc.py", "underlay.py", "interfaces.py", "attach.py", "vrfs.py", "networks.py",
         "vrf_lite.py", "topology.py", "review.py", "import_yaml.py", "tasks.py", "history.py"]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_an_imported_fabric(page):
    from nacbuilder.importer import import_folder

    p = import_folder(ROOT / "tests" / "golden").project
    at = run_page(page, p)
    assert not at.exception, at.exception
    assert at.title, f"{page} rendered no title (did the script run at all?)"


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_a_full_fabric(page):
    from tests.test_fabric_features import full_fabric

    at = run_page(page, full_fabric())
    assert not at.exception, at.exception
    assert at.title, f"{page} rendered no title (did the script run at all?)"


def test_all_scripts_compile():
    import py_compile

    for path in [ROOT / "app.py", *sorted((ROOT / "views").glob("*.py")), *sorted((ROOT / "nacbuilder").rglob("*.py"))]:
        py_compile.compile(str(path), doraise=True)
