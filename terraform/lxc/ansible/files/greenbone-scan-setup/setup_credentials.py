#!/usr/bin/env python3
"""Create the first-pass authenticated Greenbone scan objects.

This program deliberately reuses the administrator SSH keys already trusted
by the lab.  It is a pragmatic first pass: it makes no account, SSH, sudo, or
authorized_keys changes on any target.  The corresponding private keys are
provided as read-only, short-lived bind mounts by deploy-greenbone-stack.yml.

The existing CIDR scan program remains anonymous.  Credentialed Targets are
explicit host lists so a root credential can never be applied accidentally to
an arbitrary host discovered on a subnet.
"""
import os
import sys
from pathlib import Path

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]
START_TASK_NAME = os.environ.get("GREENBONE_START_TASK_NAME", "")
STATUS_TASK_NAME = os.environ.get("GREENBONE_STATUS_TASK_NAME", "")

FULL_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"
PORT_LIST_NAME = "All TCP and Nmap top 100 UDP"
ALIVE_TESTS = "ICMP, TCP-ACK Service & ARP Ping"

# `usk` is Greenbone's GMP credential type for "Username + SSH Key".
# Keep credentials per trust boundary even though the Pi account currently
# shares Steve's key material: their GVM login names and privilege models are
# different and must not be confused.
CREDENTIALS = {
    "lab-root": {
        "name": "Lab root SSH key (Steve)",
        "login": "root",
        "key_path": os.environ["GREENBONE_STEVE_KEY_PATH"],
    },
    "workstation-openvas": {
        "name": "Workstation openvas SSH key",
        "login": "openvas",
        "key_path": os.environ["GREENBONE_OPENVAS_WORKSTATION_KEY_PATH"],
    },
    "raspberry-pi-ansible": {
        "name": "Raspberry Pi ansible SSH key (Steve)",
        "login": "ansible",
        "key_path": os.environ["GREENBONE_STEVE_KEY_PATH"],
    },
}

# Only managed, known hosts belong here.  Do not replace these with CIDRs:
# Greenbone attaches an SSH credential to an entire Target.  Test fixtures,
# pve-test-vm, and deliberately vulnerable targets are intentionally absent.
TARGETS = [
    {
        "name": "Credentialed scan: managed Debian services",
        "credential": "lab-root",
        "hosts": [
            "192.168.10.163",  # ci-runner-01
            "192.168.20.110",  # authentik-stack
            "192.168.20.111",  # step-ca-stack
            "192.168.20.112",  # monitoring-stack
            "192.168.20.113",  # dns-stack
            "192.168.20.114",  # graylog-stack
            "192.168.20.120",  # portainer-stack
            "192.168.30.10",   # proxy-stack / Traefik (Tier A)
            "192.168.40.62",   # net-service-01
            "192.168.40.110",  # harbor-stack
            "192.168.40.111",  # apt-cacher-stack
            "192.168.40.112",  # netbox-stack
        ],
    },
    {
        "name": "Credentialed scan: pve hypervisor",
        "credential": "lab-root",
        "hosts": ["192.168.1.2"],
    },
    {
        "name": "Credentialed scan: Linux workstation",
        "credential": "workstation-openvas",
        "hosts": ["192.168.1.104"],
    },
    {
        "name": "Credentialed scan: Raspberry Pis",
        "credential": "raspberry-pi-ansible",
        "hosts": ["192.168.1.22", "192.168.1.23"],
    },
]


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    element = response.find(tag)
    return element.get("id") if element is not None else None


def resolve_id(gmp, getter, name, tag):
    object_id = find_by_name(gmp, getter, tag, name)
    if not object_id:
        raise RuntimeError(f"{tag} {name!r} not found on this gvmd")
    return object_id


def ensure_credential(gmp, name, login, key_path):
    existing = find_by_name(gmp, gmp.get_credentials, "credential", name)
    if existing:
        print(f"credential {name!r} already exists ({existing}), skipping")
        return existing

    private_key = Path(key_path).read_text(encoding="utf-8")
    response = gmp.create_credential(
        name=name,
        credential_type="usk",
        login=login,
        private_key=private_key,
        comment="Managed by setup_credentials.py; do not edit manually in GSA.",
    )
    credential_id = response.get("id")
    print(f"created credential {name!r} ({credential_id})")
    return credential_id


def ensure_target(gmp, name, hosts, credential_id, port_list_id):
    existing = find_by_name(gmp, gmp.get_targets, "target", name)
    if existing:
        print(f"target {name!r} already exists ({existing}), skipping")
        return existing

    response = gmp.create_target(
        name=name,
        hosts=hosts,
        ssh_credential_id=credential_id,
        alive_test=ALIVE_TESTS,
        port_list_id=port_list_id,
        comment="Managed authenticated target; intentionally explicit hosts only.",
    )
    target_id = response.get("id")
    print(f"created target {name!r} ({target_id})")
    return target_id


def ensure_task(gmp, name, config_id, target_id, scanner_id):
    existing = find_by_name(gmp, gmp.get_tasks, "task", name)
    if existing:
        print(f"task {name!r} already exists ({existing}), skipping")
        return existing
    response = gmp.create_task(
        name=name,
        config_id=config_id,
        target_id=target_id,
        scanner_id=scanner_id,
        comment="Managed authenticated task; intentionally unscheduled for first-pass validation.",
    )
    task_id = response.get("id")
    print(f"created task {name!r} ({task_id})")
    return task_id


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        credential_ids = {
            key: ensure_credential(gmp, value["name"], value["login"], value["key_path"])
            for key, value in CREDENTIALS.items()
        }
        config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        for target in TARGETS:
            target_id = ensure_target(
                gmp,
                target["name"],
                target["hosts"],
                credential_ids[target["credential"]],
                port_list_id,
            )
            ensure_task(
                gmp,
                target["name"],
                config_id,
                target_id,
                scanner_id,
            )

        if START_TASK_NAME:
            task_id = find_by_name(gmp, gmp.get_tasks, "task", START_TASK_NAME)
            if not task_id:
                raise RuntimeError(f"requested credentialed task {START_TASK_NAME!r} not found")
            gmp.start_task(task_id)
            print(f"started task {START_TASK_NAME!r} ({task_id})")

        if STATUS_TASK_NAME:
            task_id = find_by_name(gmp, gmp.get_tasks, "task", STATUS_TASK_NAME)
            if not task_id:
                raise RuntimeError(f"requested credentialed task {STATUS_TASK_NAME!r} not found")
            task = gmp.get_task(task_id)
            status = task.findtext("task/status", default="unknown")
            progress = task.findtext("task/progress", default="unknown")
            print(f"status {STATUS_TASK_NAME!r}: {status}, progress={progress}")

    print("done")


if __name__ == "__main__":
    sys.exit(main())
