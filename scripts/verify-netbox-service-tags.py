#!/usr/bin/env python3
"""Verify NetBox service objects for runtime-source tags.

Usage: ./with-secrets python3 scripts/verify-netbox-service-tags.py
"""
import json
from integrations.client import NetBoxClient

NB_VM_PATH = "/virtualization/virtual-machines/"
NB_SVC_PATH = "/ipam/services/"

nb = NetBoxClient()


def list_services_for_vm(vm_name: str) -> dict:
    print(f"\nQuerying VM: {vm_name}")
    vm_query_url = f"{nb.url}/api{NB_VM_PATH}?name={vm_name}"
    print(f"GET {vm_query_url}")
    vms = nb.get(NB_VM_PATH, name=vm_name)
    if vms.get("count", 0) == 0:
        print(f"  VM not found: {vm_name}")
        return {"vm": vm_name, "found": False, "services": []}
    vm = vms["results"][0]
    vm_id = vm.get("id")
    svc_query_url = f"{nb.url}/api{NB_SVC_PATH}?parent_object_type=virtualization.virtualmachine&parent_object_id={vm_id}"
    print(f"GET {svc_query_url}")
    svcs = nb.get(NB_SVC_PATH, parent_object_type="virtualization.virtualmachine", parent_object_id=vm_id)
    out = []
    for s in svcs.get("results", []):
        # Extract tag slugs
        tags = s.get("tags", [])
        slugs = []
        for t in tags:
            if isinstance(t, dict):
                slug = t.get("slug") or t.get("name")
                if slug:
                    slugs.append(slug)
            elif isinstance(t, str):
                slugs.append(t)
        runtime_tags = [t for t in slugs if t.startswith("runtime-source-")]
        out.append({"id": s.get("id"), "name": s.get("name"), "ports": s.get("ports"), "protocol": s.get("protocol"), "tags": slugs, "runtime_tags": runtime_tags})
    print(json.dumps({"vm": vm_name, "found": True, "vm_id": vm_id, "services": out}, indent=2))
    return {"vm": vm_name, "found": True, "vm_id": vm_id, "services": out}


if __name__ == '__main__':
    targets = [
        "docker-socket-proxy-test@pve-test",
        "gaming-stack@pve",
    ]
    results = []
    for t in targets:
        results.append(list_services_for_vm(t))
    print('\nSummary:')
    print(json.dumps(results, indent=2))
