"""Day-2 previews run nac-validate on the result on macOS, and skip it on Windows."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from nacbuilder import settings
from nacbuilder.tasks import PortSettings, set_port
from nacbuilder.validate import ValidationResult
from tests.test_fabric_features import full_fabric

ROOT = Path(__file__).resolve().parent.parent


def preview(monkeypatch, q, mac=True, windows=False):
    monkeypatch.setattr(settings, "is_macos", lambda platform=None: mac)
    monkeypatch.setattr(settings, "is_windows", lambda platform=None: windows)
    p = full_fabric()
    at = AppTest.from_file(str(ROOT / "views" / "tasks.py"), default_timeout=60)
    at.session_state["project"] = p
    import hashlib

    at.session_state["task_preview"] = {"label": "Port test", "project": q,
                                        "base": hashlib.sha256(p.model_dump_json().encode()).hexdigest()}
    return at.run()


def test_macos_runs_and_passes(monkeypatch):
    q = set_port(full_fabric(), "dc1-leaf3", 30, PortSettings(mode="access", access_vlan=2300))
    at = preview(monkeypatch, q)
    assert not at.exception
    assert any("nac-validate passes after this change" in s.value for s in at.success)
    assert at.session_state["task_preview"]["validation"].ok  # cached on the preview


def test_macos_reports_problems(monkeypatch):
    import nacbuilder.validate as v

    calls = []

    def fake(p, schema=None, rules=None):
        calls.append(p)
        return ValidationResult(ok=len(calls) > 1, output="vxlan.topology: bad thing")  # result fails, base passes

    monkeypatch.setattr(v, "nac_validate", fake)
    at = preview(monkeypatch, full_fabric().model_copy(update={"vrfs": []}))
    err = next(e for e in at.error if "nac-validate reports problems" in e.value)
    assert "already did" not in err.value
    assert any("bad thing" in c.value for c in at.code)


def test_windows_skips(monkeypatch):
    import nacbuilder.validate as v

    monkeypatch.setattr(v, "nac_validate", lambda *a, **k: pytest.fail("must not run on Windows"))
    at = preview(monkeypatch, full_fabric(), mac=False, windows=True)
    assert not at.exception
    assert any("macOS only (Windows: skipped)" in c.value for c in at.caption)
