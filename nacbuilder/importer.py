"""Read existing NaC VXLAN YAML (host_vars/<fabric>/*.yaml) into a Project.

Files are merged the way NaC merges them (dicts by key, lists concatenated). Everything
the app models becomes editable; everything else is kept in `Project.preserved` and
written back unchanged on export.
"""

import copy
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml
from pydantic import ValidationError

from . import standards as std
from .merge import merge
from .models import (
    MODES,
    Attachment,
    Interface,
    VpcPeer,
    VrfLite,
    Fabric,
    GlobalIbgp,
    Management,
    Network,
    Preserved,
    Project,
    Switch,
    Underlay,
    UnderlayGeneral,
    UnderlayIpv4,
    UnderlayMulticast,
    UnderlayOspf,
    Vrf,
)
from .tabular import fmt_errors

YAML_SUFFIXES = (".yaml", ".yml")
_VXLAN_ROOT = re.compile(r"(?m)^vxlan\s*:")
MAX_ZIP_BYTES = 50 * 1024 * 1024


@dataclass
class ImportResult:
    project: Project | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # files that were read
    skipped: list[str] = field(default_factory=list)  # YAML files without a vxlan: root


# --- YAML loading ---------------------------------------------------------------
class _Loader(yaml.SafeLoader):
    pass


def _reject_tag(loader, suffix, node):
    raise yaml.constructor.ConstructorError(
        None, None, f"the !{suffix} tag isn't supported here (resolve it before importing)", node.start_mark
    )


_Loader.add_multi_constructor("!", _reject_tag)


def parse_texts(files: dict[str, str]) -> tuple[dict, list[str]]:
    """Load and merge YAML documents from {name: text}. Returns (data, errors)."""
    data: dict = {}
    errors: list[str] = []
    for name in sorted(files):
        try:
            for doc in yaml.load_all(files[name], Loader=_Loader):
                if doc is None:
                    continue
                if not isinstance(doc, dict):
                    errors.append(f"{name}: the top level must be a mapping.")
                    continue
                data = merge(data, doc)
        except yaml.YAMLError as e:
            errors.append(f"{name}: {e}")
    return data, errors


# --- mapping data -> Project ------------------------------------------------------
def _split(d, known) -> tuple[dict, dict]:
    d = d or {}
    return {k: v for k, v in d.items() if k in known}, {k: v for k, v in d.items() if k not in known}


def _fields(cls) -> set[str]:
    return set(cls.model_fields)


def infer_border_set(name: str) -> str | None:
    """Guess client/internal/external from a border's name (e.g. dc1-border-ext1, bl-client-2)."""
    n = name.lower()
    for key, words in (("client", ("client", "cli")), ("internal", ("internal", "int")), ("external", ("external", "ext"))):
        if any(re.search(rf"(^|[-_.]){w}", n) for w in words):
            return key
    return None


_IF_FIELDS = set(Interface.model_fields) - {"switch"}


def _interface(switch: str, raw) -> tuple[Interface, dict] | None:
    """Model an interface if its mode is supported; unknown keys come back as extras."""
    if not isinstance(raw, dict) or raw.get("mode") not in MODES or not raw.get("name"):
        return None
    known, extra = _split(raw, _IF_FIELDS)
    try:
        return Interface(switch=switch, **known), extra
    except (ValidationError, TypeError):
        return None


def _vrf_lite(raw) -> VrfLite | None:
    """Model an eBGP VRF-lite profile; anything with keys beyond name/vrf/switches(name, interfaces, bgp_peers) is kept raw."""
    if not isinstance(raw, dict) or set(raw) - {"name", "vrf", "switches"}:
        return None
    for sw in raw.get("switches") or []:
        if not isinstance(sw, dict) or set(sw) - {"name", "interfaces", "bgp_peers"}:
            return None
        if any(not isinstance(i, dict) or set(i) != {"name"} for i in sw.get("interfaces") or []):
            return None
        if any(not isinstance(b, dict) or set(b) - {"address", "remote_as", "description"} for b in sw.get("bgp_peers") or []):
            return None
    try:
        return VrfLite(**raw)
    except (ValidationError, TypeError):
        return None


def project_from_data(data: dict, default_name: str | None = None) -> ImportResult:
    res = ImportResult()
    err = res.errors.append

    vx = data.get("vxlan")
    if not isinstance(vx, dict):
        err("No `vxlan:` section found.")
        return res
    ignored = sorted(k for k in data if k != "vxlan")
    if ignored:
        res.notes.append(f"Ignored top-level key(s) outside `vxlan:`: {', '.join(ignored)}.")
    vx = copy.deepcopy(vx)
    pv: dict = {"switches": {}, "vrfs": {}, "networks": {}, "attach": {}, "attach_groups": {}, "vpc_peers": {}, "interfaces": {}}

    def model(cls, raw: dict, label: str):
        try:
            return cls(**raw)
        except ValidationError as e:
            res.errors.extend(fmt_errors(e, f"{label}: "))
            return None

    # fabric + global ---------------------------------------------------------------
    fab_raw, pv["fabric"] = _split(vx.pop("fabric", None), {"name", "type"})
    glob = vx.pop("global", None) or {}
    ibgp_raw = glob.pop("ibgp", None)
    if "name" not in fab_raw:
        fab_raw["name"] = glob.get("name") or default_name or "fabric1"
    fab_raw.setdefault("type", "VXLAN_EVPN")
    fabric = model(Fabric, fab_raw, "vxlan.fabric")
    standard = std.for_fabric_type(fab_raw.get("type"))
    if standard == "non_vxlan" and ibgp_raw is None:
        ibgp_raw = glob.pop("external", None)  # External fabric: same handling, written back under `external`
    if ibgp_raw is None:
        found = ", ".join(sorted(glob)) or "nothing"
        err(f"Only iBGP VXLAN EVPN and External fabrics can be imported: `vxlan.global.ibgp` (or `external`) "
            f"is missing (found {found}).")
        return res
    pv["global_extra"] = glob
    ibgp_known, pv["ibgp"] = _split(ibgp_raw, _fields(GlobalIbgp))
    for key, item_fields in (("dns_servers", {"ip_address", "vrf"}), ("ntp_servers", {"ip_address", "vrf"}),
                             ("syslog_servers", {"ip_address", "vrf", "severity"})):
        items = ibgp_known.get(key) or []
        if any(not isinstance(i, dict) or set(i) - item_fields for i in items):
            pv["ibgp"][key] = ibgp_known.pop(key)  # has settings we don't model: keep the list as-is
            res.notes.append(f"`{key}` has settings this app doesn't edit, so it's kept unchanged.")
    ibgp = model(GlobalIbgp, ibgp_known, "vxlan.global.ibgp")

    # topology ----------------------------------------------------------------------
    topo = vx.pop("topology", None) or {}
    switches, interfaces = [], []
    for i, raw in enumerate(topo.pop("switches", None) or [], 1):
        if not isinstance(raw, dict) or not raw.get("name"):
            err(f"vxlan.topology.switches item {i}: needs a name.")
            continue
        known, extra = _split(raw, {"name", "serial_number", "role", "management"})
        if "management" in known:
            mk, me = _split(known.pop("management"), _fields(Management))
            if me:
                extra["management"] = me
            if mk:
                known["management"] = mk
        sw = model(Switch, known, f"Switch {raw['name']}")
        if sw is None:
            continue
        if sw.role == "border":
            sw.border_set = infer_border_set(sw.name)
        hw_model = ((extra.get("poap") or {}).get("preprovision") or {}).get("model")
        if hw_model:  # kept in poap (preserved) and also used for the app's port numbering
            sw.model = str(hw_model)
        raw_ifs = extra.pop("interfaces", None) or []
        kept_ifs = []
        for iface in raw_ifs:
            parsed = _interface(sw.name, iface)
            if parsed is None:
                kept_ifs.append(iface)  # mode/settings the app doesn't model: written back as-is
                continue
            obj, iextra = parsed
            interfaces.append(obj)
            if iextra:
                pv["interfaces"][obj.key] = iextra
        if kept_ifs:
            extra["interfaces"] = kept_ifs
            res.notes.append(f"{sw.name}: {len(kept_ifs)} interface(s) are kept unchanged (not editable here).")
        if extra:
            pv["switches"][sw.name] = extra
        switches.append(sw)

    vpc_peers = []
    for raw in topo.pop("vpc_peers", None) or []:
        known, extra = _split(raw, _fields(VpcPeer))
        try:
            v = VpcPeer(**known)
        except (ValidationError, TypeError):
            topo.setdefault("vpc_peers", []).append(raw)
            res.notes.append(f"vPC pair {raw.get('peer1')}/{raw.get('peer2')} is kept unchanged (not editable here).")
            continue
        vpc_peers.append(v)
        if extra:
            pv["vpc_peers"][v.key] = extra
    pv["topology"] = topo

    # underlay ----------------------------------------------------------------------
    ul = vx.pop("underlay", None) or {}
    ul_kwargs, ul_extra = {}, {}
    for sub, cls in (("general", UnderlayGeneral), ("ipv4", UnderlayIpv4), ("ospf", UnderlayOspf), ("multicast", UnderlayMulticast)):
        if sub not in ul:
            continue
        known, extra = _split(ul.pop(sub), _fields(cls))
        if extra:
            ul_extra[sub] = extra
        ul_kwargs[sub] = model(cls, known, f"vxlan.underlay.{sub}")
    ul_extra.update(ul)  # sections the app doesn't model (ipv6, isis, bgp, bfd, ...)
    pv["underlay"] = ul_extra
    underlay = Underlay(**{k: v for k, v in ul_kwargs.items() if v is not None})

    # overlay -----------------------------------------------------------------------
    ov = vx.pop("overlay", None) or {}
    vrfs, networks = [], []
    for i, raw in enumerate(ov.pop("vrfs", None) or [], 1):
        if not isinstance(raw, dict) or not raw.get("name"):
            err(f"vxlan.overlay.vrfs item {i}: needs a name.")
            continue
        known, extra = _split(raw, _fields(Vrf))
        if (v := model(Vrf, known, f"VRF {raw['name']}")) is not None:
            vrfs.append(v)
            if extra:
                pv["vrfs"][v.name] = extra
    for i, raw in enumerate(ov.pop("networks", None) or [], 1):
        if not isinstance(raw, dict) or not raw.get("name"):
            err(f"vxlan.overlay.networks item {i}: needs a name.")
            continue
        known, extra = _split(raw, _fields(Network))
        if (n := model(Network, known, f"Network {raw['name']}")) is not None:
            networks.append(n)
            if extra:
                pv["networks"][n.name] = extra

    # attach groups: rows keyed by (group, hostname), remembering which list(s) they came from
    rows: dict[tuple[str, str], dict] = {}
    for kind, key in (("vrf", "vrf_attach_groups"), ("network", "network_attach_groups")):
        for g in ov.pop(key, None) or []:
            if not isinstance(g, dict) or not g.get("name"):
                err(f"vxlan.overlay.{key}: every group needs a name.")
                continue
            gname = str(g["name"])
            _, gextra = _split(g, {"name", "switches"})
            if gextra:
                pv["attach_groups"][f"{kind}/{gname}"] = gextra
            for s in g.get("switches") or []:
                if not isinstance(s, dict) or not s.get("hostname"):
                    err(f"Attach group {gname}: every switch needs a hostname.")
                    continue
                host = str(s["hostname"])
                _, sextra = _split(s, {"hostname", "ports"})
                if sextra:
                    pv["attach"][f"{kind}/{gname}/{host}"] = sextra
                r = rows.setdefault((gname, host), {"vrf": False, "network": False, "ports": []})
                r[kind] = True
                if kind == "network":
                    r["ports"] += [str(p) for p in s.get("ports") or [] if str(p) not in r["ports"]]
    attachments = []
    for (gname, host), r in rows.items():
        used_for = "both" if r["vrf"] and r["network"] else ("vrf" if r["vrf"] else "network")
        if (a := model(Attachment, {"group": gname, "hostname": host, "ports": r["ports"], "used_for": used_for},
                       f"Attach group {gname} / {host}")) is not None:
            attachments.append(a)
    pv["overlay"] = ov

    ext = vx.pop("overlay_extensions", None) or {}
    vrf_lites = []
    for raw in ext.pop("vrf_lites", None) or []:
        lite = _vrf_lite(raw)
        if lite is None:
            ext.setdefault("vrf_lites", []).append(raw)
            res.notes.append(f"VRF-lite {raw.get('name')} uses settings this app doesn't edit (e.g. OSPF, static "
                             "routes), so it's kept unchanged.")
        else:
            vrf_lites.append(lite)
    pv["overlay_extensions"] = ext
    pv["other"] = vx  # everything left: policy, multisite, ...

    if res.errors:
        return res
    res.project = Project(
        fabric=fabric,
        ibgp=ibgp,
        switches=switches,
        underlay=underlay,
        vrfs=vrfs,
        networks=networks,
        attachments=attachments,
        vpc_peers=vpc_peers,
        interfaces=interfaces,
        vrf_lites=vrf_lites,
        preserved=Preserved(**pv),
        standard=standard,
    )
    found_roles = []
    for x in switches:
        m = re.search(r"(?i)leaf[-_]([a-z][a-z0-9]*?)[-_]?\d+$", x.name) if x.role == "leaf" else None
        if m:
            x.leaf_role = m[1].lower()
            if x.leaf_role not in found_roles:
                found_roles.append(x.leaf_role)
    if found_roles:
        res.project.leaf_roles = found_roles
        res.notes.append(f"Leaf roles guessed from names: {', '.join(found_roles)}. Check them on the Switches page.")
    supers = [s for s in switches if s.role == "super_spine"]
    allowed = std.get(standard).super_spine_counts
    if allowed and supers:
        res.project.super_spines = len(supers) if len(supers) in allowed else None
        res.notes.append(f"Found {len(supers)} super spine(s): " + (
            "the DC super spine layer is turned on." if res.project.super_spines else
            f"the {std.get(standard).label} standard allows {' or '.join(map(str, allowed))}, so the layer is left off; "
            "fix the count and turn it on on the Fabric page."))
    if standard == "non_vxlan":
        res.notes.append("This is an External fabric, so it uses the Non-VXLAN design standard.")
    else:
        res.notes.append("Imported as a DC Fabric; if this is a DMZ fabric, change the standard on the Fabric page.")

    borders = [s for s in switches if s.role == "border"]
    if borders:
        guessed = [f"{s.name} → {s.border_set}" for s in borders if s.border_set]
        unknown = [s.name for s in borders if not s.border_set]
        if guessed:
            res.notes.append(f"Border sets guessed from names: {', '.join(guessed)}. Check them on the Switches page.")
        if unknown:
            res.notes.append(f"Couldn't guess a border set for {', '.join(unknown)}; set it on the Switches page.")
    return res


# --- sources ----------------------------------------------------------------------
def _is_nac(text: str) -> bool:
    return bool(_VXLAN_ROOT.search(text))


def import_texts(files: dict[str, str], default_name: str | None = None, source: str | None = None) -> ImportResult:
    nac = {n: t for n, t in files.items() if _is_nac(t)}
    skipped = sorted(set(files) - set(nac))
    if not nac:
        res = ImportResult(errors=["No YAML file with a top-level `vxlan:` key was found."], skipped=skipped)
        return res
    data, errors = parse_texts(nac)
    if errors:
        return ImportResult(errors=errors, files=sorted(nac), skipped=skipped)
    res = project_from_data(data, default_name)
    res.files, res.skipped = sorted(nac), skipped
    if skipped:
        res.notes.append(f"Skipped file(s) without a `vxlan:` key: {', '.join(skipped)}.")
    if res.project:
        res.project.preserved.source = source
        res.project.preserved.files = sorted(nac)
    return res


def import_folder(path: Path) -> ImportResult:
    path = Path(path).expanduser()
    if not path.is_dir():
        return ImportResult(errors=[f"{path} isn't a folder."])
    files = {}
    for f in sorted(path.rglob("*")):
        if f.is_file() and f.suffix in YAML_SUFFIXES and not any(p.startswith(".") for p in f.relative_to(path).parts):
            files[f.relative_to(path).as_posix()] = f.read_text(encoding="utf-8")
    if not files:
        return ImportResult(errors=[f"No .yaml/.yml files in {path}."])
    return import_texts(files, default_name=path.name, source=str(path))


def import_uploads(uploads: list[tuple[str, bytes]]) -> ImportResult:
    """Uploaded .yaml/.yml files and/or .zip archives (e.g. the zip this app exports)."""
    files: dict[str, str] = {}
    default_name = None
    errors = []
    for name, data in uploads:
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    if sum(i.file_size for i in z.infolist()) > MAX_ZIP_BYTES:
                        errors.append(f"{name}: too large to import.")
                        continue
                    for info in z.infolist():
                        p = PurePosixPath(info.filename)
                        if info.is_dir() or p.suffix not in YAML_SUFFIXES or any(s.startswith((".", "__")) for s in p.parts):
                            continue
                        if "host_vars" in p.parts and default_name is None:
                            i = p.parts.index("host_vars")
                            default_name = p.parts[i + 1] if len(p.parts) > i + 2 else None
                        files[p.name if len(p.parts) == 1 else "/".join(p.parts[-2:])] = z.read(info).decode("utf-8")
            except zipfile.BadZipFile:
                errors.append(f"{name}: not a valid zip file.")
        else:
            try:
                files[name] = data.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"{name}: not UTF-8 text.")
    if errors:
        return ImportResult(errors=errors)
    if not files:
        return ImportResult(errors=["No YAML files were uploaded."])
    # Zip members are "<fabric>/<file>": keep just the file name when they all share a folder.
    parents = {PurePosixPath(n).parent for n in files}
    if len(parents) == 1:
        files = {PurePosixPath(n).name: t for n, t in files.items()}
    return import_texts(files, default_name=default_name, source="upload")


def find_fabric_dirs(root: Path) -> list[Path]:
    """Folders under a repo/host_vars/fabric path that hold NaC VXLAN YAML."""
    root = Path(root).expanduser()
    if not root.is_dir():
        return []

    def has_nac(d: Path) -> bool:
        for f in d.iterdir():
            if f.is_file() and f.suffix in YAML_SUFFIXES:
                try:
                    if _is_nac(f.read_text(encoding="utf-8", errors="ignore")):
                        return True
                except OSError:
                    pass
        return False

    out: list[Path] = []
    if has_nac(root):
        out.append(root)
    for base in (root / "host_vars", root):
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir() and not d.name.startswith(".") and d not in out and has_nac(d):
                    out.append(d)
    return out
