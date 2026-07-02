# Graylog and Portainer Not Working After Teardown

**Observed:** 2026-07-01
**Updated:** 2026-07-02
**Status:** Resolved. Full teardown-cycle revalidation on `pve-test-vm` passed (confirmed in
[graylog-migration-plan.md](../monitoring-stack/graylog-migration-plan.md)'s live progress
snapshot and commit `8e62e417 fix(graylog): complete cold-start teardown provisioning`,
merged via PR #387 on 2026-07-02). Kept as a troubleshooting reference for the root-cause
chain below, which remains useful if a similar cold-start regression recurs.

---

## Symptom

After a full teardown/redeploy cycle on `pve-test-vm`:

- `graylog.test.gibbsgreatly.xyz` — Bad Gateway in browser; graylog health check fails in the teardown harness.
- `portainer.test.gibbsgreatly.xyz` — Not deployed at all; Portainer is never reached in the teardown platform phase.

All other services (`authentik`, `harbor`, `grafana`, `netbox`, `traefik`) are functional.

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

There have been two distinct failure modes across the July 1 teardown work:

1. the earlier scaffold-only provision-path bug
2. the newer cold-start preflight sequencing bug

The scaffold-only bug was real and has already been fixed on the branch. The
current regression exposed by the later full teardown evidence is the second
one.

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

In the earlier failing run, the provision step did **not** start Graylog runtime
at all:

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

That earlier failure was not primarily an “external bind timing” failure. It was
a control-path mismatch:

- the teardown harness treats `graylog-stack` as a required live platform stack
- `deploy-graylog-stack.yml` still treats the real Graylog runtime as optional
- the normal `scripts/provision.sh --stack graylog-stack` path does not enable
  that runtime path
- the playbook therefore succeeds in scaffold-only mode
- the later health probe fails because no Graylog service is listening on port
  `9000`

In the later failing teardown run (`20260701-213902`), the runtime *did* start,
but `provision-graylog-stack` failed inside the Graylog preflight automation:

- `Create Graylog preflight CA` passed
- `Set Graylog certificate renewal policy` passed
- `Provision DataNode certificates` passed
- `Wait for DataNode to become AVAILABLE` retried for 30 attempts and failed
- `/api/data_nodes` kept returning a node with `status=UNCONFIGURED` and
  `datanode_status=UNCONFIGURED`

That means the playbook was waiting for `AVAILABLE` too early in the first-boot
sequence. On a brand-new Graylog stack, the DataNode is registered but stays
`UNCONFIGURED` until Graylog finishes preflight and restarts into normal mode.

### Why Graylog Shows Bad Gateway or The Wrong Login Prompt In Browser

When the teardown run leaves Graylog in scaffold-only mode, Traefik has nothing
healthy to route to, so a browser-facing “Bad Gateway” is expected.

When the teardown run reaches the newer preflight sequencing failure, Graylog is
up but still serving its setup wizard. That can surface as a direct basic-auth
dialog instead of the normal Graylog login flow backed by Authentik-configured
credentials, because post-ALIVE LDAP configuration never runs.

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

## Current State (2026-07-02)

| Stack | Status | Notes |
|---|---|---|
| graylog-stack | Targeted reprovision/redeploy path validated; full cold-start teardown path still needs revalidation | Runtime deploy succeeds, Harbor-backed images are in use, and browser access works once Graylog reaches normal mode |
| portainer-stack | Downstream teardown status still awaiting full-cycle proof | Portainer is skipped whenever the platform phase aborts at Graylog |

The original scaffold-only Graylog provision-path bug is no longer the current
working state on the branch.

The remaining teardown-specific regression was narrowed to first-boot Graylog
preflight sequencing:

- full teardown creates a truly blank Graylog LXC and blank container volumes
- targeted follow-up reprovisions do not always reproduce that exact cold-start
  state
- the failing path is therefore the one full teardown exercises: first boot of
  Graylog + DataNode on a fresh stack
- the remediation on the branch is to finalize Graylog preflight before
  requiring the DataNode to report `AVAILABLE`

Targeted validation completed after the fix:

- `graylog-stack` destroy/redeploy succeeded on `pve-test-vm`
- `graylog.test.gibbsgreatly.xyz` loaded successfully in the browser
- Graylog images pulled via Harbor-backed paths
- legacy `portainer-agent` residue on the Graylog host was identified as
  unrelated cleanup, not the root cause of the teardown failure
- the remaining open validation item is one full teardown cycle proving the
  platform phase continues through NetBox and Portainer after Graylog completes
  first-boot preflight correctly

---

## Evidence Summary

- Full teardown evidence:
  [20260701-011024](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024)
  and
  [20260701-213902](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-213902)
- Key logs:
  - [provision-graylog-stack.log](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/logs/provision-graylog-stack.log)
  - [health-graylog-stack.log](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/logs/health-graylog-stack.log)
  - [summary-deploy-platform.md](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-011024/summary-deploy-platform.md)
  - [provision-graylog-stack.log](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-213902/logs/provision-graylog-stack.log)
  - [summary-deploy-platform.md](/home/steve/git/proxmox-homelab/docs/teardown-test/artifacts/evidence/20260701-213902/summary-deploy-platform.md)

---

## Follow-On Plan (completed)

The dedicated sprint plan is at
[teardown-graylog-portainer/README.md](/home/steve/git/proxmox-homelab/docs/troubleshooting/teardown-graylog-portainer/README.md).
All steps below were completed and validated by full teardown cycle on 2026-07-02:

1. ✅ preserve the now-working Graylog runtime path and Harbor-first image routing
2. ✅ validate the new cold-start preflight sequencing fix on `pve-test-vm`
3. ✅ rerun a full teardown cycle and confirm Graylog passes in-harness
4. ✅ verify the platform phase continues through NetBox and Portainer
5. ✅ finish with browser/edge validation
