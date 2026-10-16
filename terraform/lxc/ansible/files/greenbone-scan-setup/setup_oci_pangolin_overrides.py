#!/usr/bin/env python3
"""Mark known false positives on the OCI Pangolin public edge (idempotent).

Pangolin's Next.js UI answers HTTP 200 with the app shell for most unknown paths
(`/ssl_check.php`, `/backup.zip`, ...). Greenbone's osCommerce detection treats
that 200 as "osCommerce present, version unknown", so every osCommerce NVT fires
(2026-10-16 scan: 1 Critical + 2 High, twice each). The host runs only
traefik, gerbil and pangolin. Verified 2026-10-17; see
oci/docs/vulnerability-scan-maintenance-plan.md.

Overrides are deliberately narrow: one host, one port, named NVTs. Anything else
on this host, and the same NVTs elsewhere, are still reported.
"""
import os
import sys

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]

TARGET_IP = "192.9.191.163"
PORT = "443/tcp"
FALSE_POSITIVE = -1  # GVM's severity value for "False Positive"
REASON = (
    "False positive: Pangolin (Next.js) returns HTTP 200 with the UI for unknown paths, so the "
    "osCommerce detection fires on a host that has no osCommerce. Verified 2026-10-17. "
    "Review when Pangolin or Traefik is upgraded or a vhost is added."
)

# (NVT OID, title). Add "Sensitive File Disclosure (HTTP)" (…107305) only once the paths it
# flagged are confirmed to be soft-200 responses.
OVERRIDES = [
    ("1.3.6.1.4.1.25623.1.0.100661", "osCommerce Online Merchant <= 2.2 'file_manager.php' Remote Arbitrary File Upload"),
    ("1.3.6.1.4.1.25623.1.0.100000", "osCommerce Photo Gallery SQLi Vulnerability"),
    ("1.3.6.1.4.1.25623.1.0.100099", "osCommerce 'oscid' Session Fixation Vulnerability"),
]


def existing_keys(overrides_response):
    """{(nvt_oid, host, port)} for overrides already present, from a get_overrides response."""
    keys = set()
    for override in overrides_response.findall("override"):
        nvt = override.find("nvt")
        oid = nvt.get("oid") if nvt is not None else None
        keys.add((oid, (override.findtext("hosts") or "").strip(), (override.findtext("port") or "").strip()))
    return keys


def missing_overrides(present, wanted=OVERRIDES):
    return [(oid, title) for oid, title in wanted if (oid, TARGET_IP, PORT) not in present]


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)
        present = existing_keys(gmp.get_overrides())
        todo = missing_overrides(present)
        for oid, title in todo:
            gmp.create_override(
                REASON, oid, hosts=[TARGET_IP], port=PORT, new_severity=FALSE_POSITIVE,
            )
            print(f"created override for {title!r} ({oid}) on {TARGET_IP} {PORT}")
        if not todo:
            print("all OCI Pangolin overrides already exist")
    print("done")


if __name__ == "__main__":
    sys.exit(main())
