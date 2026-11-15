# NaC VXLAN Builder

A local Streamlit wizard that asks a network engineer about a VXLAN EVPN fabric and
generates the YAML data model files for Cisco's
[Network as Code VXLAN](https://netascode.cisco.com/docs/guides/vxlan/overview/)
Ansible collection (`cisco.nac_dc_vxlan`, Nexus Dashboard 4.2).

It writes the same layout as Cisco's
[`ansible-dc-vxlan-example`](https://github.com/netascode/ansible-dc-vxlan-example) repo:

```
host_vars/<fabric>/
  global.nac.yaml             # vxlan.fabric + vxlan.global.ibgp
  topology_switches.nac.yaml  # vxlan.topology.switches
  underlay.nac.yaml           # vxlan.underlay
  vrfs.nac.yaml               # vxlan.overlay.vrfs + vrf_attach_groups
  networks.nac.yaml           # vxlan.overlay.networks + network_attach_groups
  overlay_extensions.nac.yaml # vxlan.overlay_extensions.vrf_lites (VRF-lite)
```

`topology_switches.nac.yaml` also carries `vpc_peers` and each switch's `interfaces`.

A 13-page guided tour with screenshots of a working example is in
[`docs/nac-vxlan-builder-tour.pdf`](docs/nac-vxlan-builder-tour.pdf).

## Setup

Requires Python 3.11+.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
streamlit run app.py
```

For a new fabric, work through the pages in order: **Fabric → Switches → vPC pairs → Underlay → Interfaces →
Attach groups → VRFs → Networks → VRF-lite → Topology → Review & export**. Each page has a **Save** button; nothing is kept until you save.
Use **Load example** in the sidebar to explore with a sample fabric that follows the design standard, and
**Save project (.json)** to come back to a fabric later.

### Cabling plan

The **Cabling plan** page lists what plugs into what, so the install team can work from a
spreadsheet:

- **Cabling sheet:** one row per cable: vPC peer links (paired port for port), vPC and other
  port-channel host links, access/trunk/routed host ports, and VRF-lite uplinks to the external
  routers (with dot1q tag, local IP, neighbor IP and ASN).
- **Planned spine-leaf links:** Nexus Dashboard discovers these, so they aren't in the YAML. The
  page lays them out by a rule you can change: uplink k on every leaf/border goes to spine k
  (default `Ethernet1/49-52` for 4 spines), and each spine uses the next port per leaf,
  starting at `Ethernet1/1`, leafs first, then the client, internal and external borders.
  These rows are marked `planned`.
- **Ports sheet:** every port in use on every switch: what it's for, port-channel, vPC ID,
  mode, VLANs, IP/VRF and what it connects to.
- **Conflicts:** a port used for two things (for example a VRF-lite uplink on a spine uplink
  port) is flagged.
- **Export:** an Excel workbook (Cabling, Ports, vPC pairs, VRF-lite and Notes sheets, with
  filters and frozen headers) or a zip of CSVs.

### Day-2 tasks

The **Day-2 tasks** page bundles common changes that otherwise span several pages. Each one
shows a preview first: what will be added, removed or changed, and any new check errors.
Nothing changes until you click **Apply**.

- **New tenant:** a VRF and its networks, with VLANs and VNIs allocated automatically, plus the
  attach group they use. If the group doesn't exist, it's created with every leaf. You can
  also add a VRF-lite handoff to the external borders.
- **Provision ports:** access or trunk host ports, as single ports, a port-channel per switch,
  or a vPC port-channel on a vPC pair. You can make one channel per port or bundle all ports
  into one; port-channel and vPC numbers are picked automatically.
  - **VLANs:** the access VLAN, tagged (allowed) VLANs and native VLAN can only be picked from
    the networks in the data model. The task refuses anything else, and the native VLAN is added
    to the allowed list.
  - **Other options:** description, edge port (portfast + BPDU guard), and deploying those VLANs'
    networks (and VRFs) to the switches.
  - **Ports in use:** they're refused unless you tick *Replace existing*.
  - **Checks:** a port using a VLAN that isn't a network, or a native VLAN outside the allowed
    list, gets a warning.
- **Onboard a leaf pair:** suggests the next leaf names and management IPs. It adds both leafs,
  makes them a vPC pair (peer-link ports or fabric peering), creates one vPC port-channel per
  host port on both leafs, and adds them to attach groups you choose.
- **Add VRF:** a VRF on its own, ready for VLANs. It deploys to a new group with the switches
  you pick, or to an existing attach group, optionally with a VRF-lite handoff.
- **Add VLAN:** one or more networks in an existing VRF, with VLAN and VNI picked automatically.
  - **Attach group:** they use the same group as the VRF's other VLANs unless you pick one.
  - **Trunks:** they can also be allowed on trunk ports of chosen switches (vPC peers included
    by default, optionally port-channels only). The VLAN IDs are merged into each trunk's
    allowed list, and the networks and their VRF are deployed to those switches.
- **Extend to switches:** deploys existing VLANs or VRFs to more switches. A VLAN's VRF follows it.
  If the group is shared with another VLAN or VRF, the item gets its own copy of the group, so
  nothing else moves.
- **Decommission:** removes switches, VRFs or VLANs and everything that references them:
  - **For a switch:** its interfaces, its vPC pair, attach-group rows, VRF-lite entries and kept
    imported settings. The vPC peer is removed too unless you untick that option.
  - **For a VRF:** its networks, VRF-lite profiles and sub-interfaces, and attach groups that only
    it used.
  - **For a VLAN:** the network, attach groups only it used, and (by default) its VLAN on every trunk.

When a VRF-lite handoff is added to a VRF whose attach group is shared with other VRFs or
networks, the VRF gets its own copy of that group with the borders added. That way only this
VRF is deployed to the borders.

### History and undo

- **Snapshots:** every saved change is stored as a JSON snapshot in
  `~/.nac-vxlan-builder/history/<fabric>/`, keeping the last 200 per fabric. Set
  `NACB_HISTORY_DIR` to store them elsewhere.
- **Undo/Redo:** the **Undo** and **Redo** buttons in the sidebar step through this session's changes.
- **History page:** lists every snapshot. Selecting one shows what restoring it would add back,
  remove or change. **Restore** is itself recorded, so you can undo it. You can also download a
  snapshot as a project file, or delete a fabric's history.

### Import existing YAML

Use the **Import YAML** page to edit a fabric that already lives in a NaC repo:

1. Point it at your repo, its `host_vars` folder or the fabric folder, and click **Read folder**.
   You can also upload the YAML files, or a zip like the one this app exports.
2. Review the summary and click **Load into the app**.
3. Add, change or delete switches, VRFs, networks and attach groups on their pages. To delete
   rows, tick them on the left of the table, press Delete (or click the trash icon), then **Save**.
4. On **Review & export**, write back to the same folder.

How it works:

- **Merging:** every YAML file in the folder with a top-level `vxlan:` key is read and merged
  the way NaC does it. Other files, such as Ansible connection vars, are skipped.
- **Unknown settings are kept:** anything the app doesn't edit is carried through unchanged.
  That includes interfaces, `vpc_peers`, policies, `ibgp.vpc` and extra VRF or network options
  like `arp_suppress` or `is_l2_only`. The **Kept unchanged** list shows what was found.
  If you delete or rename an item, its kept settings are dropped, and the checks tell you.
- **Output files:** the generated files always use this app's five-file layout, plus
  `other.nac.yaml` for sections like `policy`. When writing back, the app lists files that
  are now superseded (for example an `overlay.nac.yaml` you imported) and offers to delete
  them. NaC merges every file in the folder, so leaving them would bring back deleted items and
  duplicate the rest.
- **Validation:** fabrics with kept settings are validated with `nac-validate --non-strict`,
  because the bundled schema is a simplified one.
- **Attach groups:** each attach group row has a **Used for** column (`both`, `vrf` or
  `network`), so a group can have different members for VRFs and networks, as in Cisco's
  example.
- **Border sets:** the YAML has no border set field, so it's guessed from the switch name
  (`client`, `int`/`internal`, `ext`/`external`). Check it on the Switches page.
- **Not supported:** only iBGP `VXLAN_EVPN` fabrics can be imported, and `!env` or `!vault`
  tags must be resolved first.

### CSV import

The Switches, vPC pairs, Interfaces, VRFs and Networks pages each have an **Import CSV** panel:

1. Click **Download template** to get the expected headers plus example rows.
2. Fill it in (Excel is fine), and choose whether imported rows **replace** the table or are **appended**.
3. Upload it. If any line has a problem, nothing is imported and every error is listed with its
   spreadsheet line number.

| Table | Required columns | Optional columns |
|---|---|---|
| Switches | `name` | `role` (default `leaf`), `border_set` (`client`/`internal`/`external`), `leaf_role`, `model`, `serial_number`, `management_ipv4_address`, `subnet_mask_ipv4`, `default_gateway_v4` |
| VRFs | `name`, `vrf_id`, `vlan_id` | `vrf_attach_group` |
| vPC pairs | `peer1`, `peer2` | `domain_id`, `fabric_peering`, `peer1_peerlink_interfaces`, `peer2_peerlink_interfaces` (comma separated) |
| Interfaces | `switch`, `name`, `mode` | `description`, `access_vlan`, `trunk_allowed_vlans` (`10-20,50`), `native_vlan`, `members` (comma separated), `vpc_id`, `ipv4_address`, `vrf`, `dot1q_id`, `mtu`, `speed`, `enabled` |
| Networks | `name`, `vrf_name`, `net_id`, `vlan_id` | `vlan_name` (default `<name>_vlan<vlan_id>`), `gw_ip_address`, `gw_ipv6_address`, `network_attach_group`, `mtu_l3intf`, `int_desc`, `route_target_both`, `l3gw_on_border` |

Headers are case-insensitive (`Border Set` works). Blank cells mean "not set", and booleans
accept `true/yes/y/1/x`. To export a table, use the download icon on the table's toolbar.

### Leaf roles (compute, storage, ...)

On the Switches page, **Leaf roles** lets you define leaf sub-roles such as `compute, storage`.
Each leaf then gets one in the **Leaf role** column, and the rest of the app works per leaf role:

- **Counters and Quick generate:** a count per leaf role. Quick generate names leafs
  `<prefix>-leaf-compute1..N`, `<prefix>-leaf-storage1..N`.
- **Hardware:** a model per leaf role (for example 93180YC-FX for compute and 93240YC-FX2 for storage).
- **vPC pairing:** pairs leafs only within their leaf role. A mixed pair gets a warning.
- **Attach groups:** **+ group per leaf role** creates `leaf-compute`, `leaf-storage`, ..., so a
  tenant or VLAN can be deployed to storage leafs only.
- **Onboarding:** pick the leaf role for the new pair, which sets its names, model and group.
- **Diagram and cabling:** leafs are grouped and labelled by role, and spine ports are assigned
  role by role.
- **Checks:** a leaf without a role gets a warning. An undefined role, or a role on a non-leaf, is an error.
- **Import:** roles are guessed from names like `dc1-leaf-storage1`.

Leaf roles are kept in the project file, not written to the YAML.

### Hardware: Nexus 9300 models

Each switch can have a Nexus 9300 model. On the Switches page, pick one per role under
**Hardware** (spine, super spine, leaf, border, or core/edge router for a Non-VXLAN design) and
click **Apply**, or set it per switch in the **Model** column. Quick generate, onboarding and CSV
imports use these picks too.

The port numbering follows the model:

| Where | From the model |
|---|---|
| vPC pairing and onboarding | Peer link = the last two uplink ports (Ethernet1/53-54 on a 48+6 leaf, 1/59-60 on a 48+12) |
| Cabling plan | Leaf/border uplinks = the first uplink ports, one per spine. Spine ports in order per leaf. Super spine uplinks = the spine's last ports. Each port's speed is in the Ports sheet, and a spine that runs out of ports is flagged |
| VRF-lite | Default uplink = the border model's last host port |
| Interfaces page | The switch's port layout and its free host ports |
| Checks | Interfaces, port-channel members, peer links and VRF-lite ports must exist on the model (breakouts like Ethernet1/49/1 only on 40G+ ports). Mixed-speed members, mismatched peer-link speeds and different-model vPC peers get warnings |

The catalog is [`nacbuilder/data/nexus9300.yaml`](nacbuilder/data/nexus9300.yaml): 17 models with
their port groups (speed, media), roles, and host, uplink and spine port ranges. The layouts come
from Cisco's data sheets; check yours and edit or extend the file as needed. Models are kept in
the project file, not the YAML (NaC only uses a model for preprovisioning). When an imported
switch has `poap.preprovision.model`, that model is picked up.

### vPC pairs, interfaces and VRF-lite

- **vPC pairs:** **Pair automatically** pairs each border set, then the leafs in name order
  (leaf1 + leaf2, leaf3 + leaf4), using either physical peer-link ports or fabric peering. The
  checks flag a spine in a pair, a switch in two pairs, missing peer links and duplicate domain
  IDs. A border set that isn't a vPC pair gets a warning.
- **Interfaces:**
  - **Add host ports** bulk-adds access, trunk or routed ports from ranges like `Ethernet1/1-24`.
  - **Add vPC port-channel** creates the matching port-channel, with the same vPC ID, on both peers.
  - The table edits everything (access/trunk VLANs, members, vPC ID, IP and VRF, dot1q, MTU,
    speed), and you can filter it by switch.
  - The checks catch duplicate ports, ports used in two port-channels or the peer link, a vPC
    ID on only one peer or with mismatched modes, and unknown VRFs.
- **VRF-lite:** extends a VRF to external routers over eBGP on dot1q sub-interfaces. It
  defaults to the external border pair. Give it the uplink port(s), a dot1q tag (default:
  the VRF's VLAN), a link pool (`/30` or `/31`) and the neighbor ASN. The app then:
  - creates the routed parent and sub-interfaces;
  - takes the next free link subnet for each (the switch gets the first address, the neighbor the second);
  - writes `overlay_extensions.vrf_lites`;
  - attaches the VRF to those borders.
  Deleting a handoff can also remove its sub-interfaces.
- **Topology:** a diagram with spines (RR) on top, leafs in vPC pairs, the three border pairs
  below, and the VRF-lite handoff to the external routers. Switches with check errors are
  outlined in red. You can download it as SVG.

Key names for these sections follow Cisco's `cisco.nac_dc_vxlan` 0.9.1 templates.

### Review & export

- **Checks:** cross-checks the schema can't express, such as duplicate VLANs/VNIs, unknown VRFs
  or attach groups, vPC and interface conflicts, VRF-lite references, overlapping IP pools,
  and the design standard.
- **Validation:** **Run nac-validate** checks the files against `schema/schema.yaml` (extended
  to cover vPC, interfaces and VRF-lite). Under **Validation settings** you can point it at a
  full schema file, such as the one your repo's `DC_VXLAN_SCHEMA` uses. Settings are saved in
  `~/.nac-vxlan-builder.json`.
- **Cisco's semantic rules (macOS only):** these come with the `cisco.nac_dc_vxlan` Ansible collection.
  - **Install:** on macOS, **Install Cisco's rules** adds `ansible-core` to the app's environment
    and the collection to `~/.ansible/collections` (about 100 MB, from PyPI and Ansible Galaxy).
    Or do it yourself with `pip install -e ".[rules]"` and
    `ansible-galaxy collection install cisco.nac_dc_vxlan`.
  - **Running them:** once installed, Validate runs the collection's `common`, `common_vxlan` and
    `ibgp_vxlan` rule sets as well. They're Python code that runs on your Mac.
  - **Windows and Linux:** Ansible doesn't run on Windows, so the app detects that and hides the
    rules and the install button entirely. The same applies on Linux. Validation then uses the
    schema only.
- **Changes:** before anything is written you see what changes compared with the target
  folder: switches, vPC pairs, interfaces, VRFs, networks, attach groups and VRF-lite that
  are added, removed or changed. There's also a line-by-line diff of every file, including
  files that will be deleted. **Write files** stays disabled when nothing would change.
- **Export:** download a zip, or write the files into your NaC repo's `host_vars/<fabric>/`.

Then deploy from the NaC repo as usual, e.g. `ansible-playbook -i inventory.yaml vxlan.yaml`.

## Design standards

Pick the fabric's standard at the top of the **Fabric** page. It decides the NaC fabric type,
which rules the checks enforce, and which pages appear:

| Standard | NaC fabric type | Rules |
|---|---|---|
| **DC Fabric** | `VXLAN_EVPN` (iBGP) | BGP EVPN overlay, OSPF underlay, exactly 4 spines (role `spine`) that are all route reflectors, and three border pairs (role `border`): **client**, **internal** and **external** |
| **DC Fabric + super spine layer** (option) | `VXLAN_EVPN` (iBGP) | As DC Fabric, plus 2 or 4 super spines (role `super_spine`) above the 4 spines; the super spines are the route reflectors (`route_reflectors` = 2 or 4) |
| **DMZ Fabric** | `VXLAN_EVPN` (iBGP) | Same rules as DC Fabric (no super spine option) |
| **Non-VXLAN design** | `External` | Core and edge routers (`core_router` / `edge_router`) with a BGP ASN (`vxlan.global.external`), interfaces and vPC pairs. No underlay, VRFs, networks or VRF-lite: those pages and Day-2 tasks are hidden, and any leftovers are flagged instead of written |

- **Super spine layer (DC Fabric only):** turn on **Add a super spine layer** and pick 2 or 4. It affects:
  - the route reflector count;
  - **Quick generate**, which adds `<prefix>-superspine1..N`;
  - the topology diagram, which gets its own super spine row;
  - the cabling plan, which lays out spine-to-super-spine links: spine uplink k goes to super
    spine k (default from `Ethernet1/61`), and each super spine uses the next port per spine.

  Imported fabrics with 2 or 4 super spines have it turned on automatically.
- **Where it's stored:** the standard is kept in the project file, not the YAML.
- **On import:** an `External` fabric becomes Non-VXLAN design. A `VXLAN_EVPN` fabric starts as
  DC Fabric; switch it to DMZ on the Fabric page if needed.
- **Switching standards:** this changes only what's written and checked. Switching back restores
  everything.
- **Locked fields:** the UI locks the fields each standard fixes.
- **Cisco's rules:** they run the sets for the fabric type: `common` + `ibgp_vxlan` + `common_vxlan`
  for VXLAN, and `common` + `external` for External.
- **Border sets:** set each border's pair in the Switches table's *Border set* column (DC/DMZ).
  The NaC schema has no field for this, so it's stored in the project file only.

**Quick generate** on the Switches page builds the DC/DMZ layout for you (or core and edge routers for a Non-VXLAN design):
`<prefix>-spine1..4`, `<prefix>-leaf1..N`, `<prefix>-border-client1..2`,
`-border-internal1..2` and `-border-external1..2`. On the Attach groups page,
**+ border groups** creates `border-client`, `border-internal` and `border-external`.
The `all` group contains leafs only.

## Scope (v1)

- One iBGP `VXLAN_EVPN` fabric. eBGP, MSD/multisite, ISN and External fabrics aren't covered.
- Switches with management IPv4. POAP/preprovisioning, policies, breakouts, and dot1q-tunnel or
  storm-control interface settings aren't edited here. Imported ones are kept unchanged.
- VRF-lite over eBGP only. OSPF or static VRF-lite profiles are imported and kept unchanged.
- Layer-3 networks only (every network belongs to a VRF).
- Switch credentials are never written to YAML. NaC reads them from environment variables
  (`ND_*`, `NDFC_SW_USERNAME`, `NDFC_SW_PASSWORD`).

`schema/schema.yaml` is the simplified schema shipped with `ansible-dc-vxlan-example` tag 0.9.1,
extended with `vpc_peers`, interfaces and `overlay_extensions.vrf_lites`, so it covers exactly
the keys this app writes. Cisco doesn't publish the full schema in the collection. If you have
one, set it under **Validation settings**.

## Layout

```
app.py              navigation + sidebar (project save/load)
views/              one Streamlit page per wizard step
nacbuilder/models/  pydantic models; field names = NaC schema keys
nacbuilder/generate.py  Project -> YAML files (quotes ASNs, MACs, serials for YAML 1.1)
nacbuilder/checks.py    semantic cross-checks
nacbuilder/defaults.py  suggested names, VNIs, VLANs, attach groups
nacbuilder/validate.py  nac-validate wrapper (schema + rule folders)
nacbuilder/settings.py  validation settings, collection auto-detect
nacbuilder/importer.py  existing YAML -> Project (unknown settings kept)
nacbuilder/diffing.py   file diffs and added/removed/changed items
nacbuilder/diagram.py   topology SVG
nacbuilder/tasks.py     day-2 tasks (new tenant, onboard leaf pair, decommission)
nacbuilder/history.py   snapshots and undo/redo
nacbuilder/cabling.py   cabling and port plan, Excel/CSV export
nacbuilder/hardware.py  Nexus 9300 catalog (data/nexus9300.yaml) and per-model port defaults
tests/golden/       Cisco's example files, used as expected output
```

```bash
pytest
```
