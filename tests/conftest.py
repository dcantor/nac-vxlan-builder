import pytest


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """Keep project-history snapshots written during tests out of the real home folder."""
    monkeypatch.setenv("NACB_HISTORY_DIR", str(tmp_path / "history"))


@pytest.fixture(autouse=True)
def _builtin_standards(tmp_path, monkeypatch):
    """Every test starts from the built-in design standards and never writes the repo's standards file."""
    from nacbuilder import standards

    monkeypatch.setattr(standards, "STANDARDS_FILE", tmp_path / "standards.yaml")
    standards.reload()
    yield
    monkeypatch.undo()
    standards.reload()
