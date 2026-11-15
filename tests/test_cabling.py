import io
import zipfile

import pytest
from openpyxl import load_workbook

from nacbuilder.cabling import UplinkPlan, build_cabling, canon, to_csv_zip, to_xlsx, uplink_plan_for
from nacbuilder.defaults import apply_vrf_lite_plan, build_vrf_lite
from nacbuilder.models import Interface
from nacbuilder.sample import standard_example
from nacbuilder.tabular import INTERFACE_COLS, TEMPLATES, VPC_COLS, import_csv, interface_from_row, template_csv, vpc_from_row
from tests.test_fabric_features import full_fabric


@pytest.fixture
def fabric():
    """full_fabric, but with the VRF-lite uplink on Ethernet1/48 so it doesn't collide with the spine uplinks."""
    p = full_fabric()
    p.vrf_lites, p.interfaces = [], [i for i in p.interfaces if not i.name.startswith("Ethernet1/49")]
    plan = build_vrf_lite(p, "VRF01", {"dc1-border-external1": ["Ethernet1/48"], "dc1-border-external2": ["Ethernet1/48"]},
                          2000, "10.254.0.0/24", 30, 65500)
    return apply_vrf_lite_plan(p, plan)


def test_canon():
    assert canon("e1/1") == canon("Eth1/1") == canon("Ethernet1/1") == "ethernet1/1"
    assert canon("port-channel10") == "port-channel10"


def test_uplink_plan_defaults():
    p = standard_example()
    assert uplink_plan_for(p).leaf_uplinks == ["Ethernet1/49", "Ethernet1/50", "Ethernet1/51", "Ethernet1/52"]


def test_plan_contents(fabric):
    plan = build_cabling(fabric, uplink_plan_for(fabric))
    assert plan.conflicts == []
    kinds = {}
    for r in plan.links:
        kinds[r["type"]] = kinds.get(r["type"], 0) + 1
    # 10 leafs/borders x 4 spines; 5 vPC pairs x 2 peer-link ports; port-channel10 on 2 leafs; 1 access port; 2 VRF-lite uplinks
    assert kinds == {"fabric link (planned)": 40, "vPC peer link": 10, "vPC host link": 2, "access port": 1,
                     "VRF-lite uplink": 2}
    first = next(r for r in plan.links if r["source"] == "planned")
    assert first == {"type": "fabric link (planned)", "a_switch": "dc1-leaf1", "a_port": "Ethernet1/49",
                     "b_device": "dc1-spine1", "b_port": "Ethernet1/1", "detail": "spine-leaf link; ND discovers it",
                     "source": "planned"}
    # borders come after the leafs on the spines
    ext2 = [r for r in plan.links if r["a_switch"] == "dc1-border-external2" and r["source"] == "planned"]
    assert {r["b_port"] for r in ext2} == {"Ethernet1/10"}
    lite = next(r for r in plan.links if r["type"] == "VRF-lite uplink")
    assert lite["b_device"] == "External router" and "10.254.0.2 AS 65500" in lite["detail"]
    leaf1 = [r for r in plan.ports if r["switch"] == "dc1-leaf1"]
    assert [r["port"] for r in leaf1] == ["Ethernet1/1", "Ethernet1/49", "Ethernet1/50", "Ethernet1/51", "Ethernet1/52",
                                          "Ethernet1/53", "Ethernet1/54"]
    assert leaf1[0]["use"] == "vPC 10 member" and leaf1[0]["vlans"] == "2300-2310"
    assert plan.vrf_lite[0]["local_ip"] == "10.254.0.1/30"


def test_conflicts_are_reported(fabric):
    fabric.interfaces.append(Interface(switch="dc1-leaf3", name="eth1/50", mode="access", access_vlan=10))
    plan = build_cabling(fabric, uplink_plan_for(fabric))
    assert plan.conflicts == ["dc1-leaf3 Ethernet1/50 is used twice: access port and fabric uplink."]
    short = build_cabling(fabric, UplinkPlan(["Ethernet1/49", "Ethernet1/50"]))
    assert any("4 spines but only 2 uplink" in c for c in short.conflicts)
    with pytest.raises(ValueError):
        build_cabling(fabric, UplinkPlan(["Ethernet1/49"], spine_first_port="Gi0/1"))


def test_no_planned_links_when_disabled(fabric):
    plan = build_cabling(fabric, None)
    assert not any(r["source"] == "planned" for r in plan.links)


def test_exports(fabric):
    plan = build_cabling(fabric, uplink_plan_for(fabric))
    wb = load_workbook(io.BytesIO(to_xlsx(plan, "dc1")))
    assert wb.sheetnames == ["Cabling", "Ports", "vPC pairs", "VRF-lite", "Notes"]
    ws = wb["Cabling"]
    assert [c.value for c in ws[1]] == ["type", "a_switch", "a_port", "b_device", "b_port", "detail", "source"]
    assert ws.max_row == len(plan.links) + 1 and ws.freeze_panes == "A2"
    with zipfile.ZipFile(io.BytesIO(to_csv_zip(plan, "dc1"))) as z:
        assert sorted(z.namelist()) == ["dc1-cabling.csv", "dc1-ports.csv", "dc1-vpc-pairs.csv", "dc1-vrf-lite.csv"]


# --- CSV import for interfaces and vPC pairs ------------------------------------------------
def test_interface_and_vpc_templates_import():
    items, errors = import_csv(template_csv(list(INTERFACE_COLS), TEMPLATES["interfaces"]).encode(),
                               list(INTERFACE_COLS), interface_from_row)
    assert errors == [] and len(items) == 6
    assert items[2].vpc_id == 20 and items[2].members == ["Ethernet1/1"]
    pairs, errors = import_csv(template_csv(list(VPC_COLS), TEMPLATES["vpc"]).encode(), list(VPC_COLS), vpc_from_row)
    assert errors == []
    assert pairs[0].peer1_peerlink_interfaces == ["Ethernet1/53", "Ethernet1/54"] and pairs[1].fabric_peering is True


def test_interface_csv_errors_have_line_numbers():
    data = b"switch,name,mode,access_vlan\nl1,Ethernet1/1,access,10\nl1,port-channel5,trunk,\nl1,Ethernet1/2,ACCESS,5000\n"
    items, errors = import_csv(data, list(INTERFACE_COLS), interface_from_row)
    assert any(e.startswith("Line 3:") and "member ports" in e for e in errors)
    assert any(e.startswith("Line 4:") and "access_vlan" in e for e in errors)


def test_round_trip_interfaces_through_csv(fabric):
    from nacbuilder.tabular import interface_to_row

    data = template_csv(list(INTERFACE_COLS), [interface_to_row(i) for i in fabric.interfaces]).encode()
    items, errors = import_csv(data, list(INTERFACE_COLS), interface_from_row)
    assert errors == [] and items == fabric.interfaces
