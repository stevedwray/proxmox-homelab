#!/usr/bin/env python3
"""Create (and only with an explicit opt-in start) one credentialed GVM task
for the OCI Pangolin edge. The SSH key is bind-mounted only for this process.
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
KEY_PATH = os.environ["GREENBONE_OCI_PANGOLIN_AUDIT_KEY_PATH"]
START_SCAN = os.environ.get("GREENBONE_START_OCI_PANGOLIN_CREDENTIALED_SCAN", "false").lower() == "true"

TARGET_IP = "192.9.191.163"
CREDENTIAL_NAME = "OCI Pangolin Greenbone audit SSH key"
PORT_LIST_NAME = "OCI Pangolin credentialed ports"
PORT_RANGE = "T:22,80,443,U:51820,21820"
TARGET_NAME = "Credentialed scan: OCI Pangolin public edge"
TASK_NAME = "Credentialed scan: OCI Pangolin public edge"
SCAN_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"


def find_id(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    element = response.find(tag)
    return element.get("id") if element is not None else None


def require_id(gmp, getter, tag, name):
    result = find_id(gmp, getter, tag, name)
    if not result:
        raise RuntimeError(f"{tag} {name!r} not found")
    return result


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        credential_id = find_id(gmp, gmp.get_credentials, "credential", CREDENTIAL_NAME)
        if not credential_id:
            credential_id = gmp.create_credential(
                name=CREDENTIAL_NAME,
                credential_type="usk",
                login="greenbone-audit",
                private_key=Path(KEY_PATH).read_text(encoding="utf-8"),
                comment="Dedicated OCI audit key; managed by Ansible.",
            ).get("id")
            print(f"created credential {CREDENTIAL_NAME!r}")

        port_list_id = find_id(gmp, gmp.get_port_lists, "port_list", PORT_LIST_NAME)
        if not port_list_id:
            port_list_id = gmp.create_port_list(name=PORT_LIST_NAME, port_range=PORT_RANGE).get("id")
            print(f"created port list {PORT_LIST_NAME!r}")

        target_id = find_id(gmp, gmp.get_targets, "target", TARGET_NAME)
        if not target_id:
            target_id = gmp.create_target(
                name=TARGET_NAME,
                hosts=[TARGET_IP],
                ssh_credential_id=credential_id,
                port_list_id=port_list_id,
                alive_test="Consider Alive",
                comment="Single approved public edge host; no CIDR expansion.",
            ).get("id")
            print(f"created target {TARGET_NAME!r}")

        task_id = find_id(gmp, gmp.get_tasks, "task", TASK_NAME)
        if not task_id:
            task_id = gmp.create_task(
                name=TASK_NAME,
                config_id=require_id(gmp, gmp.get_scan_configs, "config", SCAN_CONFIG_NAME),
                target_id=target_id,
                scanner_id=require_id(gmp, gmp.get_scanners, "scanner", SCANNER_NAME),
                comment="Credentialed OCI audit; initially unscheduled by design.",
            ).get("id")
            print(f"created task {TASK_NAME!r}")

        if START_SCAN:
            report = gmp.start_task(task_id)
            print(f"started task {TASK_NAME!r} report={report.findtext('report_id')}")
        else:
            print(f"task {TASK_NAME!r} is ready but unscheduled and not started")


if __name__ == "__main__":
    sys.exit(main())
