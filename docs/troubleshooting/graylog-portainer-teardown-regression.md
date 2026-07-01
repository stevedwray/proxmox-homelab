# Graylog and Portainer Not Working After Teardown

**Observed:** 2026-07-01
**Status:** Root cause identified. Persistent fix not yet implemented.

---

## Symptom

After a full teardown/redeploy cycle on pve-test-vm:

- `graylog.test.gibbsgreatly.xyz` — Bad Gateway in browser; graylog health check fails in the teardown harness.
- `portainer.test.gibbsgreatly.xyz` — Not deployed at all; Portainer is never reached in the teardown platform phase.

All other services (authentik, harbor, grafana, netbox, traefik) are functional.

---

## Root Cause Chain

### Why Portainer Is Never Deployed

The teardown harness deploys the platform tier sequentially. In the failing
July 1 teardown run (`20260701-011024`), Graylog was reached after Harbor and
Monitoring and before NetBox and Portainer. When `health-graylog-stack` fails,
the platform phase aborts and the remaining stacks — including Portainer — are
never reached.

Portainer's own code is **not broken**; it simply never runs.

### Why the Graylog Health Check Fails

The teardown harness health check for `graylog-stack` is:

```bash
bash -lc "for i in \$(seq 1 24); do
  code=\$(curl -o /dev/null -s -w '%{http_code}' \
    'http://${LAB_IP_GRAYLOG}:9000/api/system/lbstatus' || true)
  body=\$(curl -fsS \
    'http://${LAB_IP_GRAYLOG}:9000/api/system/lbstatus' 2>/dev/null || true)
  echo \"attempt=\${i} http_code=\${code} body=\${body}\"
  [[ \"\${body}\" == 'ALIVE' ]] && exit 0
  sleep 5
done; echo 'Graylog did not report ALIVE after 24 attempts' >&2; exit 1"
```

This runs after `provision-graylog-stack` completes. In the failing run, the
provision step did **not** start Graylog runtime at all:

- `Write Graylog env file` was skipped
- `Write Graylog docker-compose.yml` was skipped
- `Bring up Graylog stack` was skipped
- `Wait for Graylog to report ALIVE` was skipped
- the playbook then wrote scaffold assets under `/opt/graylog-stack`

Evidence:

- [provision-graylog-stack.log](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/logs/provision-graylog-stack.log)
- [health-graylog-stack.log](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/logs/health-graylog-stack.log)

Last observed health result:

```
attempt=1 http_code=000 body=
...
attempt=24 http_code=000 body=
Graylog did not report ALIVE after 24 attempts
```

This is not primarily an “external bind timing” failure. The July 1 evidence
shows a more basic control-path mismatch:

- the teardown harness treats `graylog-stack` as a required live platform stack
- `deploy-graylog-stack.yml` still treats the real Graylog runtime as optional
- the normal `scripts/provision.sh --stack graylog-stack` path does not enable
  that runtime path
- the playbook therefore succeeds in scaffold-only mode
- the later health probe fails because no Graylog service is listening on port
  `9000`

### Why Graylog Shows Bad Gateway in Browser

When the teardown run leaves Graylog in scaffold-only mode, Traefik has
nothing healthy to route to. In that state, a browser-facing “Bad Gateway” is
consistent with the direct health failure.

This does not rule out future runtime startup or readiness issues once Graylog
is brought into the standard provision path, but those are secondary until the
runtime is actually started in teardown-driven deploys.

---

## What Was Tried

1. **Graylog-stack added to teardown inventory** (`151db69`) — correct
   direction, but it exposed that Graylog was not yet provisioned as a standard
   live runtime in teardown.

2. **Graylog inventory / host targeting fixes** (`44bbddb5`) — corrected the
   harness inventory and Graylog health host selection so the teardown was
   checking the real Graylog LXC path.

3. **Health check retry loop added** (`24ddfc5`) — added 24 × 5s retries.
   This did not fix the failure because the root problem was not late external
   binding; the runtime was never started in the failing teardown path.

4. **Live host/container inspection performed after the failing run** —
   confirmed that the Graylog LXC was running, but Graylog containers were not
   present and `/opt/graylog-stack` contained scaffold artifacts rather than a
   live compose project.

---

## Current State (2026-07-01)

| Stack | Status | Notes |
|---|---|---|
| graylog-stack | Scaffolded; runtime not started in teardown path | Health probe fails because nothing is listening on `:9000` |
| portainer-stack | Never deployed | Downstream of Graylog failure in platform phase |

The teardown test fails at the graylog health check, aborting the platform phase.

---

## Evidence Summary

- Full teardown evidence:
  [20260701-011024](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024)
- Key logs:
  - [provision-graylog-stack.log](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/logs/provision-graylog-stack.log)
  - [health-graylog-stack.log](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/logs/health-graylog-stack.log)
  - [summary-deploy-platform.md](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/summary-deploy-platform.md)

---

## Recommended Follow-On Plan

Use the dedicated sprint plan here:

[teardown-graylog-portainer/README.md](/home/steve/git/proxmox-homelab/docs/troubleshooting/teardown-graylog-portainer/README.md)

In short, the way forward is:

1. make Graylog runtime part of the standard provision path
2. add earlier Graylog-specific failure detection
3. rerun a full teardown cycle and confirm Graylog passes
4. verify the platform phase continues through NetBox and Portainer
5. finish with browser/edge validation
