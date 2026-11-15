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
