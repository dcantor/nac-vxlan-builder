"""Build Cisco Network as Code (NaC) VXLAN EVPN data model YAML files."""

__version__ = "0.1.0"

# The NaC data model this app writes for (key names follow this collection's templates).
NAC_COLLECTION = "cisco.nac_dc_vxlan"
NAC_VERSION = "0.9.1"
ND_VERSION = "4.2"  # Nexus Dashboard release the fabric settings target
