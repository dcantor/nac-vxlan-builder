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
```

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

Work through the pages in order: **Fabric → Switches → Underlay → Attach groups → VRFs →
Networks → Review & export**. Each page has a **Save** button; nothing is kept until you save.
Use **Load example** in the sidebar to explore with a sample fabric that follows the design standard, and
**Save project (.json)** to come back to a fabric later.

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

The Switches, VRFs and Networks pages each have an **Import CSV** panel:

1. Click **Download template** to get the expected headers plus example rows.
2. Fill it in (Excel is fine), and choose whether imported rows **replace** the table or are **appended**.
3. Upload it. If any line has a problem, nothing is imported and every error is listed with its
   spreadsheet line number.

| Table | Required columns | Optional columns |
|---|---|---|
| Switches | `name` | `role` (default `leaf`), `border_set` (`client`/`internal`/`external`), `serial_number`, `management_ipv4_address`, `subnet_mask_ipv4`, `default_gateway_v4` |
| VRFs | `name`, `vrf_id`, `vlan_id` | `vrf_attach_group` |
| Networks | `name`, `vrf_name`, `net_id`, `vlan_id` | `vlan_name` (default `<name>_vlan<vlan_id>`), `gw_ip_address`, `gw_ipv6_address`, `network_attach_group`, `mtu_l3intf`, `int_desc`, `route_target_both`, `l3gw_on_border` |

Headers are case-insensitive (`Border Set` works). Blank cells mean "not set", and booleans
accept `true/yes/y/1/x`. To export a table, use the download icon on the table's toolbar.

On **Review & export** you can:

- see cross-checks the schema can't express: duplicate VLANs/VNIs, unknown VRFs or attach groups,
  more route reflectors than spines, overlapping IP pools, and so on;
- run `nac-validate` against `schema/schema.yaml`;
- download a zip, or write the files straight into your NaC repo's `host_vars/<fabric>/`.

Then deploy from the NaC repo as usual, e.g. `ansible-playbook -i inventory.yaml vxlan.yaml`.

## Design standard

Every fabric must follow the house standard in `nacbuilder/standards.py`. The UI locks
these fields, and the checks flag anything that breaks them as an error:

- **Overlay:** BGP EVPN (iBGP `VXLAN_EVPN` fabric).
- **Underlay:** OSPF.
- **Spines:** exactly 4 spines with role `spine`. All 4 are route reflectors (`route_reflectors: 4`).
- **Borders:** three pairs with role `border`: **client**, **internal** and **external**.
  Set each border's pair in the Switches table's *Border set* column. The NaC schema has
  no field for this, so the pair is stored in the project file but not written to the YAML.

**Quick generate** on the Switches page builds this layout for you:
`<prefix>-spine1..4`, `<prefix>-leaf1..N`, `<prefix>-border-client1..2`,
`-border-internal1..2` and `-border-external1..2`. On the Attach groups page,
**+ border groups** creates `border-client`, `border-internal` and `border-external`.
The `all` group contains leafs only.

## Scope (v1)

- One iBGP `VXLAN_EVPN` fabric. eBGP, MSD/multisite, ISN and External fabrics aren't covered.
- Switches with management IPv4. POAP/preprovisioning, vPC pairs, interfaces and policies aren't covered.
- Layer-3 networks only (every network belongs to a VRF).
- Switch credentials are never written to YAML. NaC reads them from environment variables
  (`ND_*`, `NDFC_SW_USERNAME`, `NDFC_SW_PASSWORD`).

`schema/schema.yaml` is the simplified schema shipped with `ansible-dc-vxlan-example` tag 0.9.1,
which covers exactly the keys this app writes. The full schema ships with the
`cisco.nac_dc_vxlan` collection; point `nacbuilder.validate.nac_validate(schema=...)` at it
for a stricter check.

## Layout

```
app.py              navigation + sidebar (project save/load)
views/              one Streamlit page per wizard step
nacbuilder/models/  pydantic models; field names = NaC schema keys
nacbuilder/generate.py  Project -> YAML files (quotes ASNs, MACs, serials for YAML 1.1)
nacbuilder/checks.py    semantic cross-checks
nacbuilder/defaults.py  suggested names, VNIs, VLANs, attach groups
nacbuilder/validate.py  nac-validate wrapper
tests/golden/       Cisco's example files, used as expected output
```

```bash
pytest
```
