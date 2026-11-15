from nacbuilder.defaults import generate_switches, group_all_leafs, next_network, next_vrf
from nacbuilder.models import Project
from nacbuilder.sample import example_project
from nacbuilder.validate import nac_validate, validate_dir


def test_example_passes_nac_validate():
    res = nac_validate(example_project())
    assert res.ok, res.output


def test_generated_fabric_passes_nac_validate():
    p = Project(switches=generate_switches("dc1", 2, 2, 1, "192.0.2.11", "192.0.2.1", 24))
    p.attachments = group_all_leafs(p, ports=["Ethernet1/10"])
    p.vrfs = [next_vrf(p)]
    p.networks = [next_network(p)]
    p.underlay.general.replication_mode = "ingress"
    res = nac_validate(p)
    assert res.ok, res.output


def test_bad_file_fails(tmp_path):
    d = tmp_path / "host_vars" / "f1"
    d.mkdir(parents=True)
    (d / "global.nac.yaml").write_text("---\nvxlan:\n  fabric:\n    name: f1\n    type: NOPE\n")
    res = validate_dir(tmp_path / "host_vars")
    assert not res.ok
    assert res.output
