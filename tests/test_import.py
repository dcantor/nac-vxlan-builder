import shutil
import textwrap
from pathlib import Path

import pytest
import yaml

from nacbuilder.checks import check_project
from nacbuilder.generate import apply_write, build_documents, plan_write, render_all, zip_bytes
from nacbuilder.importer import find_fabric_dirs, import_folder, import_texts, import_uploads, infer_border_set
from nacbuilder.sample import standard_example
from nacbuilder.validate import nac_validate

GOLDEN = Path(__file__).parent / "golden"


def gold(name):
    return yaml.safe_load((GOLDEN / name).read_text())


def strip_empty_ports(doc):
    for g in doc["vxlan"]["overlay"]["network_attach_groups"]:
        for s in g["switches"]:
            if s.get("ports") == []:
                del s["ports"]
    return doc


@pytest.fixture
def cisco():
    res = import_folder(GOLDEN)
    assert res.errors == [], res.errors
    return res.project


def test_cisco_example_round_trips(cisco):
    docs = build_documents(cisco)
    assert docs["global.nac.yaml"] == gold("global.nac.yaml")
    assert docs["topology_switches.nac.yaml"] == gold("topology_switches.nac.yaml")
    assert docs["vrfs.nac.yaml"] == gold("vrfs.nac.yaml")
    assert docs["networks.nac.yaml"] == strip_empty_ports(gold("networks.nac.yaml"))
    # Underlay: everything in the original survives (ipv6 is kept as an unmodelled section).
    ul, gul = docs["underlay.nac.yaml"]["vxlan"]["underlay"], gold("underlay.nac.yaml")["vxlan"]["underlay"]
    for sec in ("general", "ipv4", "ipv6", "multicast"):
        assert gul[sec].items() <= ul[sec].items(), sec
    assert cisco.preserved.underlay == {"ipv6": gul["ipv6"]}


def test_cisco_group_all_keeps_different_vrf_and_network_members(cisco):
    used = {a.hostname: a.used_for for a in cisco.attachments if a.group == "all"}
    assert used == {"netascode-leaf1": "both", "netascode-leaf2": "both", "netascode-leaf3": "vrf", "netascode-leaf4": "vrf"}


def test_import_is_idempotent(cisco, tmp_path):
    written, _ = apply_write(cisco, tmp_path, remove_stale=False)
    again = import_folder(tmp_path).project
    a, b = cisco.model_copy(), again.model_copy()
    a.preserved = a.preserved.model_copy(update={"source": None, "files": []})
    b.preserved = b.preserved.model_copy(update={"source": None, "files": []})
    assert a == b


RICH = {
    "global.nac.yaml": """
        vxlan:
          fabric: {name: dc9, type: VXLAN_EVPN}
          global:
            ibgp:
              bgp_asn: 65009
              route_reflectors: 4
              anycast_gateway_mac: 2020.0000.00AA
              vpc: {advertise_pip: true}
              bootstrap: {enable_bootstrap: false}
    """,
    "switches.yaml": """
        vxlan:
          topology:
            switches:
              - name: s1
                role: spine
                serial_number: 123456
                routing_loopback_id: 0
                management: {management_ipv4_address: 10.9.0.1, management_ipv6_address: "2001:db8::1"}
              - name: dc9-bl-ext1
                role: border
                interfaces:
                  - {name: Ethernet1/1, mode: routed, ipv4_address: 192.0.2.1/30}
            vpc_peers:
              - {peer1: l1, peer2: l2, domain_id: 10}
    """,
    "overlay.nac.yaml": """
        vxlan:
          overlay:
            vrfs:
              - {name: PROD, vrf_id: 50001, vlan_id: 2000, vrf_attach_group: all, max_bgp_paths: 4}
            networks:
              - {name: WEB, vrf_name: PROD, net_id: 30001, vlan_id: 2300, network_attach_group: all, arp_suppress: true}
              - {name: L2ONLY, is_l2_only: true, net_id: 30002, vlan_id: 2301, network_attach_group: all}
            vrf_attach_groups:
              - name: all
                switches: [{hostname: dc9-bl-ext1}]
            network_attach_groups:
              - name: all
                switches: [{hostname: dc9-bl-ext1, ports: [Ethernet1/5], tor_ports: [{peer: t1}]}]
    """,
    "policy.nac.yaml": """
        vxlan:
          policy:
            policies: [{name: p1, template_name: switch_freeform}]
    """,
    "connection.yaml": "ansible_connection: httpapi\n",
}


@pytest.fixture
def rich():
    res = import_texts({k: textwrap.dedent(v) for k, v in RICH.items()}, source="upload")
    assert res.errors == [], res.errors
    return res


def test_unknown_settings_are_kept_and_written_back(rich):
    p = rich.project
    assert rich.skipped == ["connection.yaml"]
    assert p.switches[0].serial_number == "123456"  # unquoted number coerced to text
    assert p.ibgp.anycast_gateway_mac == "2020.0000.00aa"
    assert p.switches[1].border_set == "external"  # guessed from "-ext"
    docs = build_documents(p)
    ib = docs["global.nac.yaml"]["vxlan"]["global"]["ibgp"]
    assert ib["vpc"] == {"advertise_pip": True} and ib["bootstrap"] == {"enable_bootstrap": False}
    topo = docs["topology_switches.nac.yaml"]["vxlan"]["topology"]
    assert topo["vpc_peers"][0]["domain_id"] == 10
    s1, bl = topo["switches"]
    assert s1["routing_loopback_id"] == 0 and s1["management"]["management_ipv6_address"] == "2001:db8::1"
    assert s1["management"]["management_ipv4_address"] == "10.9.0.1"
    assert bl["interfaces"][0] == {"name": "Ethernet1/1", "mode": "routed", "ipv4_address": "192.0.2.1/30"}
    assert "border_set" not in bl
    assert [i.key for i in p.interfaces] == ["dc9-bl-ext1/Ethernet1/1"]
    assert docs["vrfs.nac.yaml"]["vxlan"]["overlay"]["vrfs"][0]["max_bgp_paths"] == 4
    nets = docs["networks.nac.yaml"]["vxlan"]["overlay"]
    assert nets["networks"][0]["arp_suppress"] is True
    assert nets["networks"][1]["is_l2_only"] is True and "vrf_name" not in nets["networks"][1]
    assert nets["network_attach_groups"][0]["switches"][0] == {
        "hostname": "dc9-bl-ext1", "ports": ["Ethernet1/5"], "tor_ports": [{"peer": "t1"}]
    }
    assert docs["other.nac.yaml"] == {"vxlan": {"policy": {"policies": [{"name": "p1", "template_name": "switch_freeform"}]}}}
    # L2-only network with is_l2_only kept is not flagged as missing a VRF.
    assert not any("L2ONLY" in i.message and "no VRF" in i.message for i in check_project(p))


def test_imported_extras_pass_nac_validate_non_strict(rich):
    res = nac_validate(rich.project)
    assert not res.strict
    assert res.ok, res.output


def test_deleting_items_drops_them_and_warns(rich):
    p = rich.project
    p.switches = [s for s in p.switches if s.name != "dc9-bl-ext1"]
    p.networks = [n for n in p.networks if n.name != "WEB"]
    msgs = [i.message for i in check_project(p)]
    assert any("dc9-bl-ext1 Ethernet1/1: switch dc9-bl-ext1 isn't in the topology" in m for m in msgs)
    assert any("Network WEB was removed or renamed" in m for m in msgs)
    docs = build_documents(p)
    names = [s["name"] for s in docs["topology_switches.nac.yaml"]["vxlan"]["topology"]["switches"]]
    assert names == ["s1"]
    assert [n["name"] for n in docs["networks.nac.yaml"]["vxlan"]["overlay"]["networks"]] == ["L2ONLY"]


def test_write_back_replaces_split_files(tmp_path):
    src = tmp_path / "dc9"
    src.mkdir()
    for name, text in RICH.items():
        (src / name).write_text(textwrap.dedent(text))
    p = import_folder(src).project
    p.vrfs[0].vlan_id = 2010  # an edit made in the GUI

    plan = plan_write(p, src)
    assert plan.stale == ["overlay.nac.yaml", "policy.nac.yaml", "switches.yaml"]
    assert plan.replace == ["global.nac.yaml"] and "connection.yaml" not in plan.stale + plan.unrelated

    apply_write(p, src, remove_stale=True)
    left = sorted(f.name for f in src.iterdir())
    assert left == sorted(["connection.yaml", *render_all(p)])
    again = import_folder(src).project
    assert again.vrfs[0].vlan_id == 2010
    assert again.preserved.other == p.preserved.other
    assert again.preserved.switches == p.preserved.switches


def test_plan_flags_app_files_that_are_no_longer_generated(tmp_path):
    p = standard_example()
    dest = tmp_path / "dc1"
    apply_write(p, dest, remove_stale=False)
    p.vrfs, p.networks = [], []  # everything deleted in the GUI
    plan = plan_write(p, dest)
    assert plan.stale == ["networks.nac.yaml", "vrfs.nac.yaml"]


def test_zip_export_imports_back():
    p = standard_example()
    res = import_uploads([("dc1-host_vars.zip", zip_bytes(p))])
    assert res.errors == []
    q = res.project
    q.preserved = p.preserved
    # Hardware models are app-only (not in the YAML), so they don't survive a YAML round trip.
    assert all(s.model is None for s in q.switches)
    p.switches = [s.model_copy(update={"model": None}) for s in p.switches]
    assert q == p


def test_find_fabric_dirs(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(GOLDEN, repo / "host_vars" / "nac-fabric1")
    (repo / "inventory.yaml").write_text("all: {}\n")
    assert find_fabric_dirs(repo) == [repo / "host_vars" / "nac-fabric1"]
    assert find_fabric_dirs(repo / "host_vars") == [repo / "host_vars" / "nac-fabric1"]
    assert find_fabric_dirs(repo / "host_vars" / "nac-fabric1") == [repo / "host_vars" / "nac-fabric1"]


@pytest.mark.parametrize(
    "files, message",
    [
        ({"a.yaml": "vxlan:\n  fabric: {name: f, type: eBGP_VXLAN}\n  global:\n    ebgp: {spine_bgp_asn: '1'}\n"},
         "Only iBGP VXLAN EVPN and External fabrics"),
        ({"a.yaml": "vxlan:\n  global:\n    ibgp: {bgp_asn: !env ASN}\n"}, "!env tag isn't supported"),
        ({"a.yaml": "vxlan: [\n"}, "a.yaml"),
        ({"a.yaml": "foo: 1\n"}, "No YAML file with a top-level `vxlan:` key"),
        ({"a.yaml": "vxlan:\n  global:\n    ibgp: {bgp_asn: x}\n"}, "bgp_asn"),
    ],
)
def test_import_errors(files, message):
    res = import_texts(files)
    assert res.project is None
    assert any(message in e for e in res.errors), res.errors


@pytest.mark.parametrize(
    "name, expected",
    [("dc1-border-client1", "client"), ("bl-int-2", "internal"), ("dc1_ext1", "external"),
     ("dc1-border-internal2", "internal"), ("border7", None), ("dc1-intl", "internal")],
)
def test_infer_border_set(name, expected):
    assert infer_border_set(name) == expected
