#!/usr/bin/env python3
"""Delete specific populate-managed NetBox objects, with guards and an archive.

Dry-run by default. Objects are named, never wildcarded, and each one must:
  - match exactly one NetBox object, and
  - carry the managed-by-proxmox-homelab ownership tag.
The full JSON of everything that will go (including cascading interfaces and
services of each VM) is written to --archive-dir before anything is deleted.

  ./with-secrets-prod scripts/netbox-delete-managed.py \
      --vm mcp-utility-stack@pve --ip 192.168.50.10/24            # dry run
  ./with-secrets-prod scripts/netbox-delete-managed.py --execute \
      --vm mcp-utility-stack@pve --ip 192.168.50.10/24

IPs are deleted before VMs. NETBOX_URL defaults to http://$LAB_IP_NETBOX:8080;
the token comes from NETBOX_API_TOKEN (or NETBOX_SUPERUSER_API_TOKEN).
Do not use populate.py --clean for this: it wipes every managed object.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MANAGED_TAG = "managed-by-proxmox-homelab"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vm", action="append", default=[], metavar="NAME", help="exact VM name, e.g. foo@pve")
    ap.add_argument("--ip", action="append", default=[], metavar="ADDR", help="exact address with prefix, e.g. 192.168.1.9/24")
    ap.add_argument("--execute", action="store_true", help="actually delete (default is a dry run)")
    ap.add_argument("--archive-dir", default=".", help="where to write the JSON archive")
    args = ap.parse_args()
    if not (args.vm or args.ip):
        ap.error("nothing to do: pass --vm and/or --ip")

    base = os.environ.get("NETBOX_URL") or f"http://{os.environ['LAB_IP_NETBOX']}:8080"
    token = os.environ.get("NETBOX_API_TOKEN") or os.environ["NETBOX_SUPERUSER_API_TOKEN"]

    def call(method: str, path: str):
        req = urllib.request.Request(f"{base.rstrip('/')}/api/{path}", method=method,
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read().decode()
                return resp.status, (json.loads(body) if body else None)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()[:300]

    def resolve(path: str, field: str, value: str) -> dict:
        status, data = call("GET", f"{path}?{field}={urllib.parse.quote(value)}")
        if status != 200:
            sys.exit(f"GUARD FAILED: lookup {path} {field}={value} -> HTTP {status}")
        exact = [o for o in data["results"] if o.get(field) == value]
        if len(exact) != 1:
            sys.exit(f"GUARD FAILED: {field}={value!r} matched {len(exact)} objects (need exactly 1)")
        obj = exact[0]
        if not any(t["slug"] == MANAGED_TAG for t in obj.get("tags", [])):
            sys.exit(f"GUARD FAILED: {field}={value!r} is not tagged {MANAGED_TAG}; refusing")
        return obj

    ips = [resolve("ipam/ip-addresses/", "address", a) for a in args.ip]
    vms = [resolve("virtualization/virtual-machines/", "name", n) for n in args.vm]
    archive = {"ips": ips, "vms": vms, "interfaces": [], "services": []}
    for vm in vms:
        archive["interfaces"] += call("GET", f"virtualization/interfaces/?virtual_machine_id={vm['id']}")[1]["results"]
        archive["services"] += call("GET", f"ipam/services/?virtual_machine_id={vm['id']}")[1]["results"]

    print(f"guards OK: {len(vms)} VMs, {len(ips)} IPs; cascading {len(archive['interfaces'])} interfaces, "
          f"{len(archive['services'])} services")
    for vm in vms:
        print(f"  vm  {vm['id']:>4} {vm['name']}")
    for ip in ips:
        print(f"  ip  {ip['id']:>4} {ip['address']}")
    path = os.path.join(args.archive_dir, f"netbox-removed-{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(archive, fh, indent=1)
    print(f"archive: {path} ({os.path.getsize(path)} bytes)")

    if not args.execute:
        print("DRY RUN: nothing deleted (add --execute)")
        return 0
    failed = 0
    for kind, path_, objs, label in (("ip", "ipam/ip-addresses/", ips, "address"),
                                     ("vm", "virtualization/virtual-machines/", vms, "name")):
        for obj in objs:
            status, _ = call("DELETE", f"{path_}{obj['id']}/")
            print(f"DELETE {kind} {obj['id']} {obj[label]} -> {status}")
            failed += status not in (200, 204)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
