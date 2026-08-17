import logging
import os
import time

from flask import Flask, jsonify, request
from gvm.connections import UnixSocketConnection
from gvm.errors import GvmError
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ.get("GVM_BRIDGE_USERNAME", "pentagi-integration")
GVM_PASSWORD = os.environ["GVM_BRIDGE_PASSWORD"]

# Confirmed present by these exact names on the live pve gvmd, 2026-08-03
# (see docs/greenbone-stack/pentagi-integration.md) -- resolved to their
# real UUIDs lazily below rather than hardcoding IDs, since they are
# instance-specific even though the names are stable community-edition
# defaults.
SCAN_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gvm-bridge")

app = Flask(__name__)

# Populated on first use, then cached for the process lifetime -- both
# objects are fixed for the life of this gvmd instance.
_ids_cache = {}


def _open_gmp():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    return Gmp(connection, transform=EtreeCheckCommandTransform())


def _resolve_ids(gmp):
    if "config_id" in _ids_cache and "scanner_id" in _ids_cache:
        return _ids_cache["config_id"], _ids_cache["scanner_id"]

    configs = gmp.get_scan_configs(filter_string=f'name="{SCAN_CONFIG_NAME}"')
    config_el = configs.find("config")
    if config_el is None:
        raise RuntimeError(f"scan config {SCAN_CONFIG_NAME!r} not found on this gvmd")

    scanners = gmp.get_scanners(filter_string=f'name="{SCANNER_NAME}"')
    scanner_el = scanners.find("scanner")
    if scanner_el is None:
        raise RuntimeError(f"scanner {SCANNER_NAME!r} not found on this gvmd")

    _ids_cache["config_id"] = config_el.get("id")
    _ids_cache["scanner_id"] = scanner_el.get("id")
    return _ids_cache["config_id"], _ids_cache["scanner_id"]


@app.errorhandler(GvmError)
def handle_gvm_error(err):
    logger.error("GMP call failed: %s", err)
    return jsonify({"error": str(err)}), 502


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    logger.exception("unexpected error")
    return jsonify({"error": str(err)}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/scan/start")
def scan_start():
    body = request.get_json(force=True, silent=True) or {}
    target_ip = body.get("target_ip")
    ports = body.get("ports")

    if not target_ip or not isinstance(target_ip, str):
        return jsonify({"error": "target_ip is required"}), 400
    if not ports or not isinstance(ports, list):
        return jsonify({"error": "ports must be a non-empty list of ints"}), 400

    suffix = str(int(time.time()))
    port_range = "T:" + ",".join(str(int(p)) for p in ports)

    with _open_gmp() as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)
        config_id, scanner_id = _resolve_ids(gmp)

        port_list = gmp.create_port_list(
            name=f"pentagi-{target_ip}-{suffix}",
            port_range=port_range,
        )
        port_list_id = port_list.get("id")

        # alive_test is hardcoded to "Consider Alive" unconditionally --
        # not something the caller can override. GVM's default host-alive
        # check relies on ICMP; every real target in this integration's
        # scope (pentest_seg's own firewalled lab targets) may not allow
        # it, and the failure mode otherwise is a scan that silently
        # finishes in ~30s with zero results that look like a clean scan.
        # See docs/greenbone-stack/plan.md Sec.4.
        target = gmp.create_target(
            name=f"pentagi-{target_ip}-{suffix}",
            hosts=[target_ip],
            port_list_id=port_list_id,
            alive_test="Consider Alive",
        )
        target_id = target.get("id")

        task = gmp.create_task(
            name=f"pentagi-{target_ip}-{suffix}",
            config_id=config_id,
            target_id=target_id,
            scanner_id=scanner_id,
        )
        task_id = task.get("id")

        report = gmp.start_task(task_id)
        report_id_el = report.find("report_id")
        report_id = report_id_el.text if report_id_el is not None else None

    return jsonify({"task_id": task_id, "report_id": report_id})


@app.get("/scan/status/<task_id>")
def scan_status(task_id):
    with _open_gmp() as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)
        response = gmp.get_task(task_id)
        task_el = response.find("task")

    if task_el is None:
        return jsonify({"error": f"task {task_id} not found"}), 404

    return jsonify(
        {
            "status": task_el.findtext("status"),
            "progress": task_el.findtext("progress"),
        }
    )


@app.get("/scan/results/<task_id>")
def scan_results(task_id):
    # get_results only -- get_reports is never called anywhere in this
    # file. A real, reproducible upstream gvmd bug crashes the daemon on
    # any get_reports call (greenbone/gvmd #2273); get_results returns
    # the same per-finding data via a different code path that works
    # fine. See docs/greenbone-stack/STACK_CONTRACT.md.
    # get_results' own task_id= kwarg only affects note/override handling,
    # not which results are returned (confirmed against python-gvm's own
    # docstring) -- scoping to this task requires the GMP filter DSL
    # instead, or every call silently returns results across all tasks.
    # rows=-1 disables GMP's default page size (10), which otherwise
    # silently truncates larger result sets.
    with _open_gmp() as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)
        response = gmp.get_results(filter_string=f"task_id={task_id} rows=-1", details=True)

    results = []
    for r in response.findall("result"):
        cve_ref = r.find('nvt/refs/ref[@type="cve"]')
        results.append(
            {
                "host": r.findtext("host"),
                "port": r.findtext("port"),
                "severity": r.findtext("severity"),
                "cve_id": cve_ref.get("id") if cve_ref is not None else None,
                "description": r.findtext("description"),
            }
        )

    return jsonify({"results": results})


@app.get("/findings/all")
def findings_all():
    # Same get_results/never-get_reports, rows=-1 reasoning as
    # /scan/results/<task_id> above -- but with NO task_id filter term at
    # all, which is what actually returns results across every task
    # (confirmed live 2026-08-17: task_id is only ever a note/override
    # scoping kwarg, not a results filter, so omitting it entirely -- not
    # passing an empty value -- is what makes this a real sweep). Used by
    # gvm_findings_ingest's scheduled sync, not by PentAGI's on-demand
    # single-task flow above; richer field extraction than scan_results()
    # to match the OpenSearch document shape in
    # docs/elasticsearch-stack/README.md section 3 -- confirmed live
    # against a real result element (not guessed) which fields actually
    # exist and at what path.
    with _open_gmp() as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)
        response = gmp.get_results(filter_string="rows=-1", details=True)

    results = []
    for r in response.findall("result"):
        nvt = r.find("nvt")
        cve_refs = nvt.findall('refs/ref[@type="cve"]') if nvt is not None else []
        hostname_el = r.find("host/hostname")
        task_el = r.find("task")
        qod_el = r.find("qod/value")
        results.append(
            {
                "finding_id": nvt.get("oid") if nvt is not None else None,
                "name": r.findtext("name"),
                "cve": [ref.get("id") for ref in cve_refs],
                "severity": r.findtext("severity"),
                "threat": r.findtext("threat"),
                "qod": qod_el.text if qod_el is not None else None,
                "host": r.findtext("host"),
                "hostname": hostname_el.text if hostname_el is not None else None,
                "port": r.findtext("port"),
                "task_name": task_el.findtext("name") if task_el is not None else None,
                "creation_time": r.findtext("creation_time"),
            }
        )

    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8010")))
