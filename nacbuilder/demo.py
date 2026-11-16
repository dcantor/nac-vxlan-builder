"""Demo mode: a simulated fabric full of sample values for showing the app's features.

The demo fabric is called `demo-dc1` (switches `demo-...`). It has 4 spines, compute and storage
leaf pairs, three border pairs, two tenants with several VLANs, vPC host ports, a disabled port
(red on the port map), and a VRF-lite handoff on the external borders. Nothing in it is real:
serials, IPs and ASNs are made up.

`delete_demo` removes everything the demo left on disk: its export folder and its history.
"""

import shutil
from pathlib import Path

from . import hardware as hw
from .history import History
from .models import Interface, ManagementServer, Project
from .paths import export_root

DEMO_NAME = "demo-dc1"


def build_demo() -> Project:
    from . import standards as std
    from .defaults import generate_switches, pair_vpc
    from .tasks import NetworkSpec, PortSpec, VrfLiteSpec, add_vlan, new_tenant, provision_ports

    p = std.new_project("dc")
    p.fabric = p.fabric.model_copy(update={"name": DEMO_NAME})
    p.leaf_roles = ["compute", "storage"]
    p.role_models = {**hw.suggested(), **p.role_models}
    p.switches = generate_switches("demo", {"compute": 4, "storage": 2}, "10.99.0.11", "10.99.0.1", 24,
                                   role_models=p.role_models, standard="dc")
    for i, s in enumerate(p.switches, 1):
        s.serial_number = f"DEMO{i:05d}"
    p.ibgp = p.ibgp.model_copy(update={
        "dns_servers": [ManagementServer(ip_address="10.99.0.53")],
        "ntp_servers": [ManagementServer(ip_address="10.99.0.123")],
    })
    p.vpc_peers = pair_vpc(p)
    p = std.apply_locks(p)

    borders = [s.name for s in p.switches if s.border_set == "external"]
    p = new_tenant(p, "PROD", [NetworkSpec("WEB", "172.20.10.1/24"), NetworkSpec("APP", "172.20.20.1/24"),
                              NetworkSpec("DB", "172.20.30.1/24")],
                   attach_group="all",
                   vrf_lite=VrfLiteSpec(switches=borders, uplinks=["Ethernet1/48"], pool="10.254.0.0/24", prefix=30,
                                        remote_as=65500))
    p = new_tenant(p, "DEV", [NetworkSpec("DEV-WEB", "172.30.10.1/24")], attach_group="all")
    p = add_vlan(p, "PROD", [NetworkSpec("BACKUP", "172.20.40.1/24")])

    vlans = {n.name: n.vlan_id for n in p.networks}
    compute = next(v.key for v in p.vpc_peers if v.peer1 == "demo-leaf-compute1")
    storage = next(v.key for v in p.vpc_peers if v.peer1 == "demo-leaf-storage1")
    p = provision_ports(p, PortSpec("Ethernet1/1-4", "trunk", vpc_pair=compute, attach="vpc",
                                    allowed_vlans=[vlans["WEB"], vlans["APP"], vlans["DB"]], description="esx-host"))
    p = provision_ports(p, PortSpec("Ethernet1/1-2", "trunk", vpc_pair=storage, attach="vpc", bundle=True,
                                    allowed_vlans=[vlans["DB"], vlans["BACKUP"]], description="storage-array"))
    p = provision_ports(p, PortSpec("Ethernet1/10-12", "access", switches=["demo-leaf-compute3"],
                                    access_vlan=vlans["DEV-WEB"], description="dev-server"))
    # one port shut down, so the port map shows a red port
    p.interfaces = [i.model_copy(update={"enabled": False, "description": "dev-server (shut)"})
                    if (i.switch, i.name) == ("demo-leaf-compute3", "Ethernet1/12") else i for i in p.interfaces]
    p.interfaces.append(Interface(switch="demo-leaf-compute4", name="Ethernet1/20", mode="access",
                                  access_vlan=vlans["APP"], enabled=False, description="spare (shut)"))
    return Project.model_validate(p.model_dump())


def is_demo(p: Project) -> bool:
    return p.fabric.name == DEMO_NAME


def demo_export_dir() -> Path:
    return export_root() / DEMO_NAME


def delete_demo(history: History | None = None) -> list[str]:
    """Delete every demo fabric: its store entry, History and export/demo-dc1/. Returns what was removed."""
    from .store import Store
    from .workspace import delete_fabric

    h = history or History()
    removed, snaps = [], 0
    for r in Store().list():
        if r.name == DEMO_NAME:
            for what in delete_fabric(r.id, history=h):
                if what.endswith("history snapshot(s)"):
                    snaps += int(what.split()[0])
                elif what.startswith("export/"):
                    removed.append(what)
    snaps += h.clear(DEMO_NAME)  # History from older versions, kept by name
    d = demo_export_dir()
    if d.is_dir() and d.resolve().parent == export_root().resolve():  # only ever export/demo-dc1
        shutil.rmtree(d)
        removed.append(f"export/{DEMO_NAME}/")
    if snaps:
        removed.append(f"{snaps} history snapshot(s)")
    return removed
