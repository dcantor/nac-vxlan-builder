from nacbuilder.checks import check_project
from nacbuilder.models import Project
from nacbuilder.sample import standard_example
from nacbuilder.tabular import (
    NETWORK_COLS,
    SWITCH_COLS,
    TEMPLATES,
    VRF_COLS,
    import_csv,
    network_from_row,
    switch_from_row,
    template_csv,
    vrf_from_row,
)

TABLES = {
    "switches": (SWITCH_COLS, switch_from_row),
    "vrfs": (VRF_COLS, vrf_from_row),
    "networks": (NETWORK_COLS, network_from_row),
}


def test_templates_import_cleanly():
    for name, (cols, fn) in TABLES.items():
        items, errors = import_csv(template_csv(list(cols), TEMPLATES[name]).encode(), list(cols), fn)
        assert errors == [], (name, errors)
        assert len(items) == len(TEMPLATES[name])


def test_switch_csv_with_excel_quirks():
    # BOM, mixed-case headers with spaces, partial columns, uppercase values, Excel "24.0".
    data = (
        "﻿Name,Role,Border Set,Serial_Number,management_ipv4_address,subnet_mask_ipv4\n"
        "dc1-spine1,SPINE,,FDO1,10.0.0.1,24.0\n"
        "dc1-border-ext1,border,External,FDO2,10.0.0.2,24\n"
        ",,,,,\n"
    ).encode()
    items, errors = import_csv(data, list(SWITCH_COLS), switch_from_row)
    assert errors == []
    assert [(s.name, s.role, s.border_set) for s in items] == [
        ("dc1-spine1", "spine", None),
        ("dc1-border-ext1", "border", "external"),
    ]
    assert items[0].management.subnet_mask_ipv4 == 24


def test_network_csv_booleans_and_defaults():
    data = (
        "name,vrf_name,net_id,vlan_id,route_target_both,l3gw_on_border\n"
        "N1,VRF01,30001,2300,yes,FALSE\n"
        "N2,VRF01,30002,2301,,\n"
    ).encode()
    items, errors = import_csv(data, list(NETWORK_COLS), network_from_row)
    assert errors == []
    assert items[0].route_target_both is True and items[0].l3gw_on_border is None
    assert items[1].route_target_both is None
    assert items[0].vlan_name == "N1_vlan2300"


def test_errors_use_spreadsheet_line_numbers():
    data = "name,vrf_id,vlan_id\nGOOD,50001,2000\nBAD NAME,abc,5000\n".encode()
    items, errors = import_csv(data, list(VRF_COLS), vrf_from_row)
    assert [v.name for v in items] == ["GOOD"]  # the UI saves nothing while errors exist
    assert errors and all(e.startswith("Line 3:") for e in errors), errors
    assert any("vrf_id" in e for e in errors) and any("vlan_id" in e for e in errors)


def test_unknown_and_empty_files():
    _, errors = import_csv(b"name,colour\nx,red\n", list(VRF_COLS), vrf_from_row)
    assert "Unknown column(s): colour" in errors[0]
    _, errors = import_csv(b"", list(VRF_COLS), vrf_from_row)
    assert errors == ["The file is empty."]
    _, errors = import_csv(b"name,vrf_id,vlan_id\n", list(VRF_COLS), vrf_from_row)
    assert errors == ["The file has no data rows."]


def test_round_trip_through_csv_keeps_project_clean():
    """Export each table as CSV, re-import it, and the project is unchanged and still clean."""
    p = standard_example()
    from nacbuilder.tabular import switch_to_row

    sw_csv = template_csv(list(SWITCH_COLS), [switch_to_row(s) for s in p.switches]).encode()
    vrf_csv = template_csv(list(VRF_COLS), [v.to_nac() for v in p.vrfs]).encode()
    net_csv = template_csv(list(NETWORK_COLS), [n.to_nac() for n in p.networks]).encode()
    sw, e1 = import_csv(sw_csv, list(SWITCH_COLS), switch_from_row)
    vrfs, e2 = import_csv(vrf_csv, list(VRF_COLS), vrf_from_row)
    nets, e3 = import_csv(net_csv, list(NETWORK_COLS), network_from_row)
    assert e1 == e2 == e3 == []
    q = Project(fabric=p.fabric, ibgp=p.ibgp, underlay=p.underlay, attachments=p.attachments,
                switches=sw, vrfs=vrfs, networks=nets)
    assert q == p
    assert check_project(q) == []
