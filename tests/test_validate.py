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
    for sub in ("common", "common_vxlan", "ibgp_vxlan", "ebgp_vxlan"):
        (coll / sub).mkdir(parents=True)
    assert [d.name for d in rule_dirs(coll)] == ["common", "common_vxlan", "ibgp_vxlan"]
    assert rule_dirs(RULES) == [RULES]
    monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", str(tmp_path))
    assert [d.name for d in resolve_rules(Settings())] == ["common", "common_vxlan", "ibgp_vxlan"]
    assert resolve_rules(Settings(use_rules=False)) == []
    cfg = tmp_path / "cfg.json"
    save_settings(Settings(schema_path="/x.yaml", rules_path=str(RULES)), cfg)
    assert load_settings(cfg) == Settings(schema_path="/x.yaml", rules_path=str(RULES))
    assert load_settings(tmp_path / "missing.json") == Settings()
