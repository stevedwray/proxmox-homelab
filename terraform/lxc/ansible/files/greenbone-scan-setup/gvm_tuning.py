#!/usr/bin/env python3
"""GVM scan tuning and supervision helper -- docs/gvm-scan-redesign/runbook.md.

Runs inside the greenbone-stack compose's throwaway gvm-tools container (the
playbook gvm-scan-tuning.yml copies it to /opt/greenbone-stack and runs it with
GVM_USERNAME/GVM_PASSWORD in the environment). Names that do not start with
"Credentialed scan: " or "LAN scan: " get the "Credentialed scan: " prefix.

Read-only modes:
  report                  every credentialed task: status, scan start/end, and per host
                          SSH-login/LSC result counts (one fetch, tallied locally)
  status                  the same task list without the per-host tally
  prefs <task>            the task's preferences (max_hosts, max_checks, ...)
  listsched               every task that has a schedule
  times <name-fragment>   last report start/end of tasks whose name matches
  taskinfo <task>         target hosts/excludes, alive tests, preferences, results by host
  credinfo <task>         task status and whether its target carries an SSH credential
  lancheck                every "LAN scan: " task: status, exclude count, max_hosts, schedule
  hostresults <task> <ip> every recorded result for one host (login/OS/LSC detail)
  vulns <task>            non-Log findings of a task, grouped by host and severity
  compare <zone>...       non-Log findings of "Credentialed scan: <zone>" vs "LAN scan: <zone> full-vuln"
  families                the scan-config families and test counts of "Full and fast"
  portlist                shape of the "All TCP and Nmap top 100 UDP" port list

Changing modes (the playbook asks for TASK_APPROVAL on production):
  start <task>            start one task
  stop <task>             stop one task and wait for it to leave Running/Stop Requested
  setprefs <task> k=v...  set task preferences (a live test only: the setup scripts reset them)
  unschedule <task>       remove one task's schedule
  unschedule_all          remove EVERY schedule (a deploy with the credential-program or
                          schedule-program tags re-attaches them)
  runhosts <zone> <ip[:skipPORT]>...
                          one temporary single-host task per ip, cloned from the zone task,
                          run one after another; ":skip8200" scans without that port; each
                          temporary task, target and port list is deleted afterwards
  seq <zone>...           run whole zone tasks one after another and print per-host results
  cleanup                 stop and delete every "TEMP calibrate " task and target
                          (kill the background runner first, or it starts the next host)

Known GVM quirks this works around: get_reports crashes in this feed, so results come
from get_results; the GMP name~ filter combined with task_id= is ignored, so names are
tallied locally.
"""
import os
import sys
import time
from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

PREFIX = "Credentialed scan: "


def tasks(gmp):
    root = gmp.get_tasks(filter_string=f'name~"{PREFIX}" rows=-1')
    for t in root.findall("task"):
        yield t


def info(t):
    lr = t.find("last_report/report")
    return {
        "name": t.findtext("name"), "id": t.get("id"), "status": t.findtext("status"),
        "progress": t.findtext("progress"),
        "start": lr.findtext("scan_start") if lr is not None else None,
        "end": lr.findtext("scan_end") if lr is not None else None,
        "hosts": (t.findtext("target/hosts") or ""),
    }


def auth_counts(gmp, task_id):
    """One fetch, tallied locally: the GMP name~ filter combined with task_id was ignored."""
    r = gmp.get_results(filter_string=f"task_id={task_id} rows=-1")
    per = {}
    for res in r.findall("result"):
        host = res.findtext("host") or "?"
        host = host.strip().split("\n")[0].strip()
        name = res.findtext("name") or ""
        d = per.setdefault(host, {"failed": 0, "ok": 0, "lsc": 0, "total": 0})
        d["total"] += 1
        if "SSH Login Failed" in name:
            d["failed"] += 1
        elif "SSH Login Successful" in name:
            d["ok"] += 1
        elif "Authenticated Scan" in name or "Local Security Check" in name:
            d["lsc"] += 1
    return per


def find(gmp, name):
    if not name.startswith((PREFIX, "LAN scan: ")):
        name = PREFIX + name
    root = gmp.get_tasks(filter_string=f'name~"{name}" rows=-1')
    return next((info(t) for t in root.findall("task") if t.findtext("name") == name), None)


def run_sequence(gmp, zones):
    """Start each zone only after the previous one finished, so durations are solo."""
    for z in zones:
        t = find(gmp, z)
        if t is None or t["status"] in ("Running", "Requested", "Queued"):
            print(f"SKIP {z}: {'missing' if t is None else t['status']}", flush=True)
            continue
        gmp.start_task(t["id"])
        t0 = time.time()
        print(f"{time.strftime('%H:%M:%S')} started {z}", flush=True)
        time.sleep(30)
        while find(gmp, z)["status"] in ("Running", "Requested", "Queued", "Stop Requested"):
            time.sleep(60)
        t = find(gmp, z)
        print(f"{time.strftime('%H:%M:%S')} {z}: {t['status']} in {(time.time() - t0) / 60:.0f} min"
              f" (gvm start={t['start']} end={t['end']})", flush=True)
        for h, d in sorted(auth_counts(gmp, t["id"]).items()):
            print(f"      {h:16} {d}", flush=True)


ALIVE = "ICMP, TCP-ACK Service & ARP Ping"
BUSY = ("Running", "Requested", "Queued", "Stop Requested")


def run_hosts(gmp, zone, ips):
    """One temporary single-host task per ip, cloned from the zone's task/target."""
    base = find(gmp, zone)
    t = gmp.get_task(base["id"]).find("task")
    config = t.find("config").get("id")
    scanner = t.find("scanner").get("id")
    tg = gmp.get_target(t.find("target").get("id")).find("target")
    port_list = tg.find("port_list").get("id")
    ssh = tg.find("ssh_credential").get("id")
    for spec in ips:
        ip, _, skip = spec.partition(":skip")
        name = f"TEMP calibrate {ip}"
        target_id = task_id = temp_pl = None
        try:
            if skip:
                n = int(skip)
                temp_pl = gmp.create_port_list(name=f"TEMP ports minus {n} {int(time.time())}",
                                               port_range=f"T:1-{n - 1},{n + 1}-65535").get("id")
                print(f"{time.strftime('%H:%M:%S')} {ip}: using port list without {n}", flush=True)
            target_id = gmp.create_target(name=name, hosts=[ip], ssh_credential_id=ssh,
                                          alive_test=ALIVE, port_list_id=temp_pl or port_list).get("id")
            task_id = gmp.create_task(name=name, config_id=config, target_id=target_id,
                                      scanner_id=scanner, preferences={"max_hosts": "1"}).get("id")
            gmp.start_task(task_id)
            t0 = time.time()
            print(f"{time.strftime('%H:%M:%S')} started {ip}", flush=True)
            time.sleep(30)
            while gmp.get_task(task_id).findtext("task/status") in BUSY:
                time.sleep(60)
            status = gmp.get_task(task_id).findtext("task/status")
            print(f"{time.strftime('%H:%M:%S')} {ip}: {status} in {(time.time() - t0) / 60:.0f} min", flush=True)
            for h, d in sorted(auth_counts(gmp, task_id).items()):
                print(f"      {h:16} {d}", flush=True)
        except Exception as exc:  # keep going with the remaining hosts
            print(f"{time.strftime('%H:%M:%S')} {ip}: ERROR {type(exc).__name__}: {exc}", flush=True)
        finally:
            if task_id:
                gmp.delete_task(task_id, ultimate=True)
            if target_id:
                gmp.delete_target(target_id, ultimate=True)
            if temp_pl:
                gmp.delete_port_list(temp_pl, ultimate=True)


def main():
    mode = sys.argv[1]
    conn = UnixSocketConnection(path=os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock"))
    with Gmp(conn, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(os.environ["GVM_USERNAME"], os.environ["GVM_PASSWORD"])
        if mode == "setprefs":
            t = find(gmp, sys.argv[2])
            prefs = dict(a.split("=", 1) for a in sys.argv[3:])
            gmp.modify_task(t["id"], preferences=prefs)
            print(f"set {prefs} on {t['name']}")
            return
        if mode in ("listsched", "unschedule_all"):
            n = 0
            for t in gmp.get_tasks(filter_string="rows=-1").findall("task"):
                sch = t.find("schedule")
                if sch is None or not sch.get("id") or sch.get("id") == "0":
                    continue
                n += 1
                print(f"{t.findtext('name'):50} {t.findtext('status'):10} schedule={sch.findtext('name')}")
                if mode == "unschedule_all":
                    gmp.modify_task(t.get("id"), schedule_id="0")
            print(f"{n} scheduled task(s)" + (" -- all unscheduled" if mode == "unschedule_all" else ""))
            return
        if mode == "prefs":
            t = find(gmp, sys.argv[2])
            task = gmp.get_task(t["id"]).find("task")
            for pr in task.findall("preferences/preference"):
                print(f"{pr.findtext('scanner_name') or pr.findtext('name')} = {pr.findtext('value')}")
            print(f"status={task.findtext('status')} schedule={task.findtext('schedule/name')} hosts={task.findtext('target/name')}")
            return
        if mode == "hostresults":
            t = find(gmp, sys.argv[2])
            want = sys.argv[3]
            r = gmp.get_results(filter_string=f"task_id={t['id']} rows=-1")
            for res in r.findall("result"):
                host = (res.findtext("host") or "").strip().split("\n")[0].strip()
                if host != want:
                    continue
                nvt = res.find("nvt")
                print(f"{res.findtext('threat') or '':8} {res.findtext('port') or '':14} {res.findtext('name')[:70]} [{nvt.get('oid') if nvt is not None else ''}]")
                nm = res.findtext("name") or ""
                if any(k in nm for k in ("Authenticated", "Local Security", "OS Detection", "Determine OS", "LSC", "SSH Authorization", "Hostname", "Detection (HTTP)")):
                    for line in (res.findtext("description") or "").splitlines()[:14]:
                        print("      | " + line[:150])
            return
        if mode == "portlist":
            pl = gmp.get_port_lists(filter_string='name="All TCP and Nmap top 100 UDP"').find("port_list")
            root = gmp.get_port_list(pl.get("id"))
            for pr in list(root.iter("port_range"))[:6]:
                print("range:", pr.findtext("start"), pr.findtext("end"), pr.findtext("type"))
            print("total ranges:", len(list(root.iter("port_range"))))
            return
        if mode == "times":
            root = gmp.get_tasks(filter_string=f'name~"{sys.argv[2]}" rows=-1')
            for t in root.findall("task"):
                lr = t.find("last_report/report")
                print(f"{t.findtext('name'):40} {t.findtext('status'):10} start={lr.findtext('scan_start') if lr is not None else None} end={lr.findtext('scan_end') if lr is not None else None}")
            return
        if mode == "taskinfo":
            t = find(gmp, sys.argv[2])
            task = gmp.get_task(t["id"]).find("task")
            tg = gmp.get_target(task.find("target").get("id")).find("target")
            print("target hosts:", (tg.findtext("hosts") or "")[:80], "| exclude:", (tg.findtext("exclude_hosts") or "")[:80])
            print("alive_tests:", tg.findtext("alive_tests"), "| max_hosts/max_checks:", [(p.findtext("scanner_name"), p.findtext("value")) for p in task.findall("preferences/preference")][:3])
            r = gmp.get_results(filter_string=f"task_id={t['id']} rows=-1")
            hosts = {}
            for res in r.findall("result"):
                h = (res.findtext("host") or "").strip().split("\n")[0].strip()
                hosts[h] = hosts.get(h, 0) + 1
            print("results by host:", dict(sorted(hosts.items())) or "none")
            return
        if mode == "compare":
            def findings(task_name):
                t = find(gmp, task_name)
                if t is None:
                    return None
                out = {}
                for res in gmp.get_results(filter_string=f"task_id={t['id']} rows=-1").findall("result"):
                    if (res.findtext("threat") or "") in ("Log", ""):
                        continue
                    host = (res.findtext("host") or "").strip().split("\n")[0].strip()
                    nvt = res.find("nvt")
                    key = (host, nvt.get("oid") if nvt is not None else res.findtext("name"))
                    out[key] = (res.findtext("threat"), (res.findtext("name") or "")[:70])
                return out
            for zone in sys.argv[2:]:
                cred, full = findings(f"Credentialed scan: {zone}"), findings(f"LAN scan: {zone} full-vuln")
                if cred is None or full is None or not full:
                    print(f"== {zone}: skipped (cred={cred is not None}, full={None if full is None else len(full)})")
                    continue
                ch, fh = {h for h, _ in cred}, {h for h, _ in full}
                common_hosts = {h for h, _ in cred} | set()
                # compare only hosts that BOTH tasks scanned (any result, incl. clean hosts)
                both_hosts = {h for h, _ in cred} & {h for h, _ in full}
                cset = {k for k in cred if k[0] in both_hosts or True}
                shared_scope = lambda d: {k for k in d if k[0] in (ch | fh)}
                only_c = {k for k in cred if k not in full and k[0] in fh | ch}
                only_f = {k for k in full if k not in cred}
                both = {k for k in cred if k in full}
                print(f"== {zone}: vulns(non-Log) cred={len(cred)} full={len(full)} | in both={len(both)} only-credentialed={len(only_c)} only-full-vuln={len(only_f)}")
                print(f"   hosts with vulns: cred={sorted(ch)} full={sorted(fh)}")
                for label, keys, src in (("only-cred", only_c, cred), ("only-full", only_f, full)):
                    for k in sorted(keys)[:6]:
                        print(f"   {label}: {k[0]:15} {src[k][0]:8} {src[k][1]}")
            return
        if mode == "credinfo":
            for name in sys.argv[2:]:
                t = find(gmp, name)
                task = gmp.get_task(t["id"]).find("task")
                tg = gmp.get_target(task.find("target").get("id")).find("target")
                cred = tg.find("ssh_credential")
                elev = tg.find("ssh_elevate_credential")
                print(f"{name}: status={task.findtext('status')} progress={task.findtext('progress')} "
                      f"ssh_credential={(cred.findtext('name') if cred is not None and cred.get('id') else None)} "
                      f"elevate={(elev.findtext('name') if elev is not None and elev.get('id') else None)}")
            return
        if mode == "families":
            cfg = gmp.get_scan_configs(filter_string='name="Full and fast"').find("config")
            root = gmp.get_scan_config(cfg.get("id"), tasks=False).find("config")
            fams = root.findall("families/family")
            print(f"config id {cfg.get('id')}: {len(fams)} families; family_count={root.findtext('family_count')} nvt_count={root.findtext('nvt_count')}")
            rows = []
            for f in fams:
                rows.append((int(f.findtext("nvt_count") or 0), f.findtext("name"), f.findtext("max_nvt_count"), f.findtext("growing")))
            for n, name, mx, gr in sorted(rows, reverse=True)[:40]:
                print(f"  {n:6} / {mx:>6}  growing={gr}  {name}")
            return
        if mode == "lancheck":
            for t in sorted(gmp.get_tasks(filter_string='name~"LAN scan: " rows=-1').findall("task"), key=lambda x: x.findtext("name")):
                full = gmp.get_task(t.get("id")).find("task")
                tg = gmp.get_target(full.find("target").get("id")).find("target")
                excl = [e for e in (tg.findtext("exclude_hosts") or "").split(",") if e.strip()]
                prefs = {p.findtext("scanner_name"): p.findtext("value") for p in full.findall("preferences/preference")}
                sched = full.find("schedule")
                print(f"{full.findtext('name'):36} {full.findtext('status'):9} excl={len(excl):2} max_hosts={prefs.get('max_hosts'):>3} sched={sched.findtext('name') if sched is not None and sched.get('id') else None}")
            return
        if mode == "vulns":
            t = find(gmp, sys.argv[2])
            per = {}
            hosts_seen = set()
            for res in gmp.get_results(filter_string=f"task_id={t['id']} rows=-1").findall("result"):
                host = (res.findtext("host") or "").strip().split("\n")[0].strip()
                hosts_seen.add(host)
                threat = res.findtext("threat") or ""
                if threat in ("Log", ""):
                    continue
                per.setdefault(host, []).append((threat, (res.findtext("name") or "")[:60]))
            print(f"{t['name']}: {len(hosts_seen)} hosts with any result, {len(per)} with non-Log findings")
            order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
            for host in sorted(per, key=lambda h: tuple(int(x) for x in h.split(".")) if h.replace(".", "").isdigit() else (999,)):
                counts = {}
                for threat, _ in per[host]:
                    counts[threat] = counts.get(threat, 0) + 1
                worst = sorted(per[host], key=lambda x: order.get(x[0], 9))[:2]
                print(f"  {host:16} {dict(sorted(counts.items(), key=lambda kv: order.get(kv[0], 9)))}  e.g. {'; '.join(w[1] for w in worst)}")
            return
        if mode == "cleanup":
            root = gmp.get_tasks(filter_string='name~"TEMP calibrate " rows=-1')
            for t in root.findall("task"):
                if t.findtext("status") in BUSY:
                    gmp.stop_task(t.get("id"))
                    print(f"stop requested: {t.findtext('name')}")
            for _ in range(40):
                busy = [t for t in gmp.get_tasks(filter_string='name~"TEMP calibrate " rows=-1').findall("task")
                        if t.findtext("status") in BUSY]
                if not busy:
                    break
                time.sleep(15)
            for t in gmp.get_tasks(filter_string='name~"TEMP calibrate " rows=-1').findall("task"):
                gmp.delete_task(t.get("id"), ultimate=True)
                print(f"deleted task: {t.findtext('name')}")
            for tg in gmp.get_targets(filter_string='name~"TEMP calibrate " rows=-1').findall("target"):
                gmp.delete_target(tg.get("id"), ultimate=True)
                print(f"deleted target: {tg.findtext('name')}")
            print("cleanup done")
            return
        if mode == "runhosts":
            run_hosts(gmp, sys.argv[2], sys.argv[3:])
            return
        if mode == "unschedule":
            t = find(gmp, sys.argv[2])
            gmp.modify_task(t["id"], schedule_id="0")
            print(f"removed schedule from {t['name']}")
            return
        if mode == "seq":
            run_sequence(gmp, sys.argv[2:])
            return
        if mode == "stop":
            t = find(gmp, sys.argv[2])
            if t is None:
                sys.exit(f"no task named {sys.argv[2]!r}")
            gmp.stop_task(t["id"])
            for _ in range(36):
                status = gmp.get_task(t["id"]).findtext("task/status")
                if status not in BUSY:
                    break
                time.sleep(5)
            print(f"stopped {t['name']}: status now {status}")
            return
        if mode == "start":
            t = find(gmp, sys.argv[2])
            if t is None:
                sys.exit(f"no task named {sys.argv[2]!r}")
            name = t["name"]
            if t["status"] in ("Running", "Requested", "Queued"):
                sys.exit(f"{name} already {t['status']}")
            gmp.start_task(t["id"])
            print(f"started {name}")
            return
        for t in tasks(gmp):
            i = info(t)
            line = f"{i['name']:45} {i['status']:10} {i['progress'] or '':>4}% start={i['start']} end={i['end']}"
            if mode == "report" and i["start"]:
                print(line)
                for h, d in sorted(auth_counts(gmp, i["id"]).items()):
                    print(f"      {h:16} {d}")
                continue
            print(line)


main()
