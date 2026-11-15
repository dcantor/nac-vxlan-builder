from pathlib import Path

import pytest
import yaml

from nacbuilder.generate import build_documents, render_all, write_host_vars, zip_bytes
from nacbuilder.sample import example_project

GOLDEN = Path(__file__).parent / "golden"


def load(name: str) -> dict:
    return yaml.safe_load((GOLDEN / name).read_text())


@pytest.fixture
def files():
    # Parse with PyYAML (YAML 1.1, like Ansible) to catch type surprises.
    return {k: yaml.safe_load(v) for k, v in render_all(example_project()).items()}


def test_global_matches_cisco_example(files):
    assert files["global.nac.yaml"] == load("global.nac.yaml")


def test_topology_matches_cisco_example(files):
    assert files["topology_switches.nac.yaml"] == load("topology_switches.nac.yaml")


def test_vrfs_and_networks_match_cisco_example(files):
    assert files["vrfs.nac.yaml"]["vxlan"]["overlay"]["vrfs"] == load("vrfs.nac.yaml")["vxlan"]["overlay"]["vrfs"]
    assert (
        files["networks.nac.yaml"]["vxlan"]["overlay"]["networks"]
        == load("networks.nac.yaml")["vxlan"]["overlay"]["networks"]
    )


def test_attach_groups_only_include_used_groups(files):
    vrf_groups = {g["name"] for g in files["vrfs.nac.yaml"]["vxlan"]["overlay"]["vrf_attach_groups"]}
    assert vrf_groups == {"all", "leaf1", "leaf2"}
    net = {g["name"]: g for g in files["networks.nac.yaml"]["vxlan"]["overlay"]["network_attach_groups"]}
    assert net["all"]["switches"][0] == {"hostname": "netascode-leaf1", "ports": ["Ethernet1/13", "Ethernet1/14"]}
    assert net["leaf1"]["switches"] == [{"hostname": "netascode-leaf1"}]


def test_underlay_matches_cisco_example_where_set(files):
    gen = files["underlay.nac.yaml"]["vxlan"]["underlay"]
    gold = load("underlay.nac.yaml")["vxlan"]["underlay"]
    assert gen["ipv4"] == gold["ipv4"]
    assert gen["ospf"] == {"area_id": "0.0.0.0", "authentication_enable": False}
    for k, v in gold["general"].items():
        if k != "enable_ipv6_underlay":
            assert gen["general"][k] == v, k


def test_ingress_replication_drops_multicast_sections():
    p = example_project()
    p.underlay.general.replication_mode = "ingress"
    p.underlay.general.routing_protocol = "is-is"
    u = build_documents(p)["underlay.nac.yaml"]["vxlan"]["underlay"]
    assert "multicast" not in u and "ospf" not in u
    assert "underlay_rp_loopback_ip_range" not in u["ipv4"]


def test_risky_strings_are_quoted():
    p = example_project()
    p.ibgp.anycast_gateway_mac = "12:34:56:12:34:56"  # sexagesimal int in YAML 1.1
    p.switches[0].serial_number = "12345"
    p.switches[1].name = "yes"
    text = render_all(p)
    g = yaml.safe_load(text["global.nac.yaml"])
    t = yaml.safe_load(text["topology_switches.nac.yaml"])["vxlan"]["topology"]["switches"]
    assert g["vxlan"]["global"]["ibgp"]["anycast_gateway_mac"] == "12:34:56:12:34:56"
    assert g["vxlan"]["global"]["ibgp"]["bgp_asn"] == "65001"
    assert t[0]["serial_number"] == "12345"
    assert t[1]["name"] == "yes"


def test_empty_project_has_only_global_and_underlay():
    from nacbuilder.models import Project

    assert list(render_all(Project())) == ["global.nac.yaml", "underlay.nac.yaml"]


def test_write_and_zip(tmp_path):
    p = example_project()
    written = write_host_vars(p, tmp_path)
    assert {w.name for w in written} == {f.name for f in GOLDEN.glob("*.nac.yaml")}
    assert all(w.parent == tmp_path / "host_vars" / "nac-fabric1" for w in written)
    assert len(zip_bytes(p)) > 500
