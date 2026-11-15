import pytest


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """Keep project-history snapshots written during tests out of the real home folder."""
    monkeypatch.setenv("NACB_HISTORY_DIR", str(tmp_path / "history"))
