from pathlib import Path

from nacbuilder.defaults import generate_switches, group_all_leafs, groups_per_border_set, next_network, next_vrf
from nacbuilder.models import Project
from nacbuilder.sample import example_project, standard_example
from nacbuilder.validate import nac_validate, validate_dir


def test_example_passes_nac_validate():
    res = nac_validate(example_project())
    assert res.ok, res.output


def test_generated_fabric_passes_nac_validate():
    p = Project(switches=generate_switches("dc1", 2, "192.0.2.11", "192.0.2.1", 24))
    p.attachments = group_all_leafs(p, ports=["Ethernet1/10"]) + groups_per_border_set(p)
    p.vrfs = [next_vrf(p)]
    p.networks = [next_network(p)]
    p.underlay.general.replication_mode = "ingress"
    res = nac_validate(p)
    assert res.ok, res.output


def test_standard_example_passes_nac_validate():
    """border_set is app-only metadata; it must not leak into the YAML (strict schema)."""
    res = nac_validate(standard_example())
    assert res.ok, res.output


def test_bad_file_fails(tmp_path):
    d = tmp_path / "host_vars" / "f1"
    d.mkdir(parents=True)
    (d / "global.nac.yaml").write_text("---\nvxlan:\n  fabric:\n    name: f1\n    type: NOPE\n")
    res = validate_dir(tmp_path / "host_vars")
    assert not res.ok
    assert res.output


RULES = Path(__file__).parent / "rules"


def test_rules_folder_runs_after_schema():
    p = standard_example()
    res = nac_validate(p, rules=[RULES])
    assert res.ok, res.output
    assert res.rules == [str(RULES)]
    p.switches[0].name = "DC1-SPINE1"
    res = nac_validate(p, rules=[RULES])
    assert not res.ok
    assert "rule 900" in res.output and "DC1-SPINE1" in res.output


def test_full_schema_is_strict(tmp_path):
    from nacbuilder.validate import SCHEMA

    full = tmp_path / "full.yaml"
    full.write_text(SCHEMA.read_text())  # stand-in for a full schema file
    res = nac_validate(standard_example(), schema=full)
    assert res.ok and res.strict and res.schema == str(full)


def test_settings_and_rule_dirs(tmp_path, monkeypatch):
    from nacbuilder.settings import Settings, load_settings, resolve_rules, rule_dirs, save_settings

    coll = tmp_path / "ansible_collections/cisco/nac_dc_vxlan/roles/validate/files/rules"
    for sub in ("common", "common_vxlan", "ibgp_vxlan", "ebgp_vxlan", "external"):
        (coll / sub).mkdir(parents=True)
    assert [d.name for d in rule_dirs(coll)] == ["common", "ibgp_vxlan", "common_vxlan"]
    assert [d.name for d in rule_dirs(coll, "External")] == ["common", "external"]
    assert rule_dirs(RULES) == [RULES]
    monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", str(tmp_path))
    assert [d.name for d in resolve_rules(Settings())] == ["common", "ibgp_vxlan", "common_vxlan"]
    assert [d.name for d in resolve_rules(Settings(), fabric_type="External")] == ["common", "external"]
    assert resolve_rules(Settings(use_rules=False)) == []
    cfg = tmp_path / "cfg.json"
    save_settings(Settings(schema_path="/x.yaml", rules_path=str(RULES)), cfg)
    assert load_settings(cfg) == Settings(schema_path="/x.yaml", rules_path=str(RULES))
    assert load_settings(tmp_path / "missing.json") == Settings()


# --- Cisco rules: macOS only ---------------------------------------------------------------
def test_rules_only_on_macos(tmp_path, monkeypatch):
    from nacbuilder.settings import Settings, is_windows, resolve_rules, rules_supported

    coll = tmp_path / "ansible_collections/cisco/nac_dc_vxlan/roles/validate/files/rules"
    (coll / "common").mkdir(parents=True)
    monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", str(tmp_path))
    assert rules_supported("darwin") and not rules_supported("win32") and not rules_supported("linux")
    assert is_windows("win32") and is_windows("cygwin") and not is_windows("darwin")
    assert [d.name for d in resolve_rules(Settings(), platform="darwin")] == ["common"]
    assert resolve_rules(Settings(), platform="win32") == []
    assert resolve_rules(Settings(rules_path=str(coll)), platform="win32") == []


def test_collection_version(tmp_path):
    import json

    from nacbuilder.settings import collection_version

    root = tmp_path / "ansible_collections/cisco/nac_dc_vxlan"
    rules = root / "roles/validate/files/rules"
    rules.mkdir(parents=True)
    (root / "MANIFEST.json").write_text(json.dumps({"collection_info": {"version": "0.9.1"}}))
    assert collection_version(rules) == "0.9.1"
    assert collection_version(tmp_path / "nope/a/b/c/d") is None


def test_install_cisco_rules(monkeypatch, tmp_path):
    import subprocess

    import nacbuilder.settings as settings

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(settings.subprocess, "run", fake_run)
    monkeypatch.setattr(settings, "find_collection_rules", lambda: tmp_path)
    monkeypatch.setattr(settings.sys, "platform", "darwin")
    res = settings.install_cisco_rules()
    assert res.ok
    assert calls[0][1:] == ["-m", "pip", "install", settings.ANSIBLE_SPEC]
    assert calls[1][0].endswith("ansible-galaxy") and calls[1][1:] == ["collection", "install", "cisco.nac_dc_vxlan"]

    calls.clear()
    monkeypatch.setattr(settings.sys, "platform", "win32")
    res = settings.install_cisco_rules()
    assert not res.ok and calls == [] and "macOS" in res.log


def test_install_reports_failure(monkeypatch):
    import subprocess

    import nacbuilder.settings as settings

    monkeypatch.setattr(settings.sys, "platform", "darwin")
    monkeypatch.setattr(settings.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="network down"))
    res = settings.install_cisco_rules()
    assert not res.ok and "network down" in res.log
