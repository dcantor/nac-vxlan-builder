"""Table <-> model conversion shared by the data editors and CSV import (no Streamlit here)."""

import csv
import io
import math
import re
from typing import Callable

import pandas as pd
from pydantic import ValidationError

from .models import Management, Network, Switch, Vrf

TRUE_WORDS = {"true", "yes", "y", "1", "x"}

# Column keys and pandas dtypes for each table. CSV headers use the same keys.
SWITCH_COLS = {
    "name": "string",
    "role": "string",
    "border_set": "string",
    "serial_number": "string",
    "management_ipv4_address": "string",
    "subnet_mask_ipv4": "Int64",
    "default_gateway_v4": "string",
}
VRF_COLS = {"name": "string", "vrf_id": "Int64", "vlan_id": "Int64", "vrf_attach_group": "string"}
NETWORK_COLS = {
    "name": "string",
    "vrf_name": "string",
    "net_id": "Int64",
    "vlan_id": "Int64",
    "vlan_name": "string",
    "gw_ip_address": "string",
    "gw_ipv6_address": "string",
    "network_attach_group": "string",
    "mtu_l3intf": "Int64",
    "int_desc": "string",
    "route_target_both": "bool",
    "l3gw_on_border": "bool",
}


# --- cell / row helpers -------------------------------------------------------
def clean(v):
    """Normalise a cell: blanks/NaN -> None, numpy scalars -> Python, 3.0 -> 3, '24.0' -> '24'."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float):
        if math.isnan(v):
            return None
        if v.is_integer():
            return int(v)
    if isinstance(v, str):
        v = v.strip()
        if re.fullmatch(r"\d+\.0+", v):  # Excel likes to write 24 as 24.0
            v = v.split(".")[0]
        return v or None
    return v


def records(df: pd.DataFrame) -> list[dict]:
    rows = [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]
    return [r for r in rows if any(v not in (None, False) for v in r.values())]


def fmt_errors(e: ValidationError, prefix: str = "") -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = re.sub(r"^Value error, ", "", err["msg"])
        out.append(f"{prefix}{loc + ': ' if loc else ''}{msg}")
    return out


def build_rows(rows: list[dict], fn: Callable[[dict], object], label: str) -> tuple[list, list[str]]:
    items, errors = [], []
    for i, r in enumerate(rows, 1):
        try:
            items.append(fn({k: v for k, v in r.items() if v is not None}))
        except ValidationError as e:
            errors += fmt_errors(e, f"{label} row {i}: ")
        except (ValueError, TypeError) as e:
            errors.append(f"{label} row {i}: {e}")
    return items, errors


# --- per-table converters -----------------------------------------------------
def switch_to_row(s: Switch) -> dict:
    m = s.management.to_nac() if s.management else {}
    return {"name": s.name, "role": s.role, "border_set": s.border_set, "serial_number": s.serial_number, **m}


def switch_from_row(r: dict) -> Switch:
    r = dict(r)
    mgmt = {k: r.pop(k) for k in ("management_ipv4_address", "subnet_mask_ipv4", "default_gateway_v4") if k in r}
    if isinstance(r.get("role"), str):
        r["role"] = r["role"].lower()
    if isinstance(r.get("border_set"), str):
        r["border_set"] = r["border_set"].lower()
    return Switch(**r, management=Management(**mgmt) if mgmt else None)


def vrf_from_row(r: dict) -> Vrf:
    return Vrf(**r)


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in TRUE_WORDS
    return bool(v)


def network_from_row(r: dict) -> Network:
    r = dict(r)
    for flag in ("route_target_both", "l3gw_on_border"):
        if _truthy(r.get(flag)):
            r[flag] = True
        else:
            r.pop(flag, None)  # unchecked = leave unset (ND default false)
    r.setdefault("vlan_name", f"{r.get('name')}_vlan{r.get('vlan_id')}")
    return Network(**r)


# --- CSV ----------------------------------------------------------------------
def _norm_header(h: str) -> str:
    return re.sub(r"[\s-]+", "_", str(h).strip().lower())


def read_csv(data: bytes, columns: list[str]) -> tuple[list[dict], list[str]]:
    """Parse CSV bytes into cleaned row dicts limited to `columns`. Returns (rows, errors)."""
    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str, encoding="utf-8-sig", skipinitialspace=True)
    except pd.errors.EmptyDataError:
        return [], ["The file is empty."]
    except (pd.errors.ParserError, UnicodeDecodeError) as e:
        return [], [f"Can't read the file as CSV: {e}"]
    df.columns = [_norm_header(c) for c in df.columns]
    unknown = sorted(set(df.columns) - set(columns))
    if unknown:
        return [], [f"Unknown column(s): {', '.join(unknown)}. Expected: {', '.join(columns)}."]
    dups = sorted({c for c in df.columns if list(df.columns).count(c) > 1})
    if dups:
        return [], [f"Duplicate column(s): {', '.join(dups)}."]
    return records(df.reindex(columns=columns)), []


def import_csv(data: bytes, columns: list[str], from_row: Callable[[dict], object]) -> tuple[list, list[str]]:
    rows, errors = read_csv(data, columns)
    if errors:
        return [], errors
    if not rows:
        return [], ["The file has no data rows."]
    # Row numbers in messages match the spreadsheet (header is line 1).
    items, errors = build_rows(rows, from_row, "CSV")
    return items, [re.sub(r"^CSV row (\d+)", lambda m: f"Line {int(m[1]) + 1}", e) for e in errors]


def template_csv(columns: list[str], examples: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    for ex in examples:
        w.writerow({c: ex.get(c, "") for c in columns})
    return buf.getvalue()


TEMPLATES = {
    "switches": [
        {"name": "dc1-spine1", "role": "spine", "serial_number": "FDO24000001",
         "management_ipv4_address": "10.1.1.11", "subnet_mask_ipv4": 24, "default_gateway_v4": "10.1.1.1"},
        {"name": "dc1-leaf1", "role": "leaf", "serial_number": "FDO24000005",
         "management_ipv4_address": "10.1.1.15", "subnet_mask_ipv4": 24, "default_gateway_v4": "10.1.1.1"},
        {"name": "dc1-border-client1", "role": "border", "border_set": "client", "serial_number": "FDO24000009",
         "management_ipv4_address": "10.1.1.19", "subnet_mask_ipv4": 24, "default_gateway_v4": "10.1.1.1"},
    ],
    "vrfs": [
        {"name": "VRF01", "vrf_id": 50001, "vlan_id": 2000, "vrf_attach_group": "all"},
        {"name": "VRF02", "vrf_id": 50002, "vlan_id": 2001, "vrf_attach_group": "all"},
    ],
    "networks": [
        {"name": "NET01", "vrf_name": "VRF01", "net_id": 30001, "vlan_id": 2300, "gw_ip_address": "172.16.10.1/24",
         "network_attach_group": "all", "route_target_both": "false", "l3gw_on_border": "false"},
        {"name": "NET02", "vrf_name": "VRF01", "net_id": 30002, "vlan_id": 2301, "vlan_name": "app_vlan2301",
         "gw_ip_address": "172.16.11.1/24", "network_attach_group": "all", "mtu_l3intf": 9216,
         "int_desc": "App tier", "route_target_both": "false", "l3gw_on_border": "true"},
    ],
}
