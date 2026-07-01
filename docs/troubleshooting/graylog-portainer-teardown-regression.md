# Graylog and Portainer Not Working After Teardown

**Observed:** 2026-07-01
**Status:** Unresolved. Investigation stopped; report written for follow-up.

---

## Symptom

After a full teardown/redeploy cycle on pve-test-vm:

- `graylog.test.gibbsgreatly.xyz` — Bad Gateway in browser; graylog health check fails in the teardown harness.
- `portainer.test.gibbsgreatly.xyz` — Not deployed at all; Portainer is never reached in the teardown platform phase.

All other services (authentik, harbor, grafana, netbox, traefik) are functional.

---

## Root Cause Chain

### Why Portainer Is Never Deployed

The teardown harness deploys the platform tier sequentially. Graylog-stack was added to the tier in this session at position 10 (after monitoring, before netbox and portainer). When the graylog health check fails, `phase_deploy_platform` aborts and the remaining stacks — including portainer — are never reached.

Portainer's own code is **not broken**; it simply never runs.

### Why the Graylog Health Check Fails

The teardown harness health check for graylog-stack is:

```bash
curl -fsS 'http://${LAB_IP_GRAYLOG}:9000/api/system/lbstatus' | grep -qx 'ALIVE'
```

This runs immediately after `provision-graylog-stack` completes. The provision playbook waits for Graylog to report ALIVE, but does so via `http://127.0.0.1:9000` **from within the LXC** — not from the external network. The harness health check runs from the **operator's machine** against the external LXC IP.

Last observed error:

```
curl: (7) Failed to connect to 192.168.20.114:9000 after 0 ms: Could not connect to server
```

Immediate connection refused (0 ms) suggests the port is not yet externally bound at the moment the check fires, even though the provision considers Graylog ALIVE via localhost.

A 2-minute retry loop (24 × 5s) was added in commit `24ddfc5` but this was not validated in a full teardown run before the investigation was halted.

### Why Graylog Shows Bad Gateway in Browser

Even when Graylog deploys and the harness health check doesn't abort the run prematurely, the browser shows "Bad Gateway" from Traefik. This was observed in one run where provision passed. Likely cause: Traefik routes to `http://192.168.20.114:9000` but Graylog is either still initialising on the external port, or the Graylog container is not running.

Not yet root-caused definitively. Graylog is a heavy Java application with multiple components (datanode, MongoDB, OpenSearch/datanode). Startup takes longer than lighter stacks and the ordering within the provision may not wait long enough for all components.

---

## What Was Tried

1. **Graylog-stack added to teardown inventory** (`151db69`) — correct decision but introduced a cascade failure because of the health check timing issue.

2. **Health check retry loop added** (`24ddfc5`) — adds 24 × 5s retries. Not yet confirmed to resolve the issue in a full run.

3. **No investigation into why Graylog itself is not externally reachable** — the teardown was halted before this could be diagnosed. Possible causes:
   - Docker port binding on `0.0.0.0:9000` takes longer than expected after provision "ALIVE" check
   - One of the multiple Graylog components (datanode, OpenSearch) is failing post-startup
   - The compose file has a port binding issue (e.g., bound to LXC-internal interface only)

---

## Current State (2026-07-01)

| Stack | Status | Notes |
|---|---|---|
| graylog-stack | Provisioned; externally unreachable | Bad gateway; health check fails |
| portainer-stack | Never deployed | Downstream of graylog failure |

The teardown test fails at the graylog health check, aborting the platform phase.

---

## Suggested Next Steps (not yet attempted)

1. **Validate the retry fix**: run the teardown again with the `24ddfc5` retry loop and observe whether Graylog eventually becomes reachable externally or still fails.

2. **Check Graylog container state directly** after a provision run:
   ```bash
   PVE_ENV=pve-test-vm ./with-secrets ssh root@192.168.20.114 \
     "docker ps; docker logs graylog-stack-graylog-1 --tail 50"
   ```

3. **Check if port 9000 is externally bound** after provision:
   ```bash
   PVE_ENV=pve-test-vm ./with-secrets ssh root@192.168.20.114 "ss -tlnp | grep 9000"
   ```

4. **If port is externally bound but Graylog is still unhealthy**: investigate the datanode/OpenSearch startup sequence — Graylog 6.x requires the datanode to complete certificate provisioning before it reports ALIVE from outside.

5. **If the retry loop is insufficient**: consider moving the graylog health check out of `validate_stack_smoke` into a dedicated post-provision smoke test that can tolerate the full Java startup window (~3–5 minutes).
