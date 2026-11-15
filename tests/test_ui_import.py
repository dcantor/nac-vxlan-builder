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
