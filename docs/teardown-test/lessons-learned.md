# Teardown Test Lessons Learned

This document captures durable lessons from teardown/redeploy rehearsal work so
future cycles do not need to rediscover the same failure modes from raw
evidence directories.

## Lessons

### 1. Protect shared SDN resources during destroy

- Early rehearsal runs exposed a destroy-side effect where shared SDN subnet
  resources could be removed while later operations still depended on them.
- Future teardown work should preserve the current guardrail that prevents
  subnet deletion unless the safe VNET conditions are met.
- Any change to destroy-hook behavior should be treated as high risk and
  revalidated with a full teardown/redeploy cycle before promotion.

### 2. Use the explicit Authentik URL for reconciler workflows

- The reconciler's default Authentik target produced discovery HTTP 404 during
  early rehearsal flows (OP-25). Do not rely on the default.
- The harness now uses the internal HTTPS endpoint with the homelab root CA:

  ```bash
  AUTHENTIK_EXTRA_CA=certs/homelab-root.crt \
  ./with-secrets python3 terraform/lxc/reconcile-edge.py \
    --authentik-url "https://authentik-int.${LAB_DOMAIN}:9443" --json
  ```

  This is used by `live-preflight`, `activate-edge`, and `final-validation`.
- The earlier `http://${lab_ip_authentik}:9000 --no-verify-tls` form worked
  when step-ca was not yet integrated; it is superseded by the HTTPS form above.
- Rehearsal and runbook commands must specify the URL explicitly — do not
  assume the reconciler default is safe.

### 3. Validate Portainer directly on port 9000

- An earlier OP-28 validation probe used the wrong direct endpoint and created
  a false failure signal.
- The correct direct Portainer API probe is:

  ```bash
  curl -fsS http://${lab_ip_portainer}:9000/api/system/status
  ```

- Future final-validation steps should use this endpoint when checking Portainer
  directly.

### 4. Treat step-ca root certificate drift as an explicit decision

- `certs/homelab-root.crt` changed after step-ca rebuild activity.
- This is not routine evidence noise; it is a policy decision point about
  whether the public root certificate is intentionally tracked and whether CA
  continuity is expected across rebuilds.
- Do not silently stage or ignore this file during teardown-test closeout.

### 5. Approval packet details matter more than approval prose

- Several failed rehearsal runs were caused by an overly strict approval-text
  matcher rather than infrastructure defects.
- The detailed control surface belongs in the approval packet: target, commit,
  rollback window, service evidence, and recreatable-service acknowledgement.
- Future rehearsals should keep the human approval text simple and reuse the
  packet structure for the detailed scope record.

### 6. Most raw evidence is only useful as forensic history

- Timestamped `state.json` files and phase logs are valuable for debugging a
  specific failed run, but most are not durable source material.
- During interrupted or abnormal runs, `state.json` may be incomplete or stale.
  In that situation, phase logs are the primary source of truth.
- The most reusable artifacts are:
  - tracked closeout summaries,
  - stamped successful full-cycle evidence directories,
  - approval-packet examples,
  - concise notes about fixes and operator decisions.

### 7. Recovery work should start read-only

- When a teardown or redeploy run leaves the environment in a partial state,
  first capture a read-only inventory and service snapshot before deciding on a
  rebuild or cleanup path.
- Record the decision path explicitly before any follow-on mutation so a later
  session does not have to infer operator intent from incomplete evidence.

### 8. Cold-start: Harbor is unavailable when Stage 3a stacks deploy

- Stage 3a (edge) deploys before Stage 3b (platform), which includes Harbor.
- Stacks that declare Harbor proxy-cache image paths in `docker-compose.yml`
  will fail `docker compose up` on a cold deploy because Harbor does not exist yet.
- Fix: add a reachability check (`nc -z`) before compose up. If Harbor is
  unreachable, pre-pull images from their public origin registries and tag them
  with the Harbor proxy-cache paths, then use `pull: "never"` in the compose task.
- This pattern was applied to `deploy-authentik-stack.yml`. Apply the same pattern
  to any future stack that references Harbor registry paths in its compose file.

### 9. Portainer "local" endpoint does not match by name

- Portainer registers its own Docker daemon as an endpoint named "local" with
  URL `unix:///var/run/docker.sock`.
- The NetBox populate script matched Portainer endpoints to LXC containers by
  name or IP. "local" never matches any container name, and the unix socket
  URL yields no IP for the IP index.
- Fix: resolve the `portainer_url` hostname at populate time and assign that IP
  to any unix-socket endpoint. The LXC hosting Portainer is then matched by IP.
- Do not filter out unix-socket endpoints from `get_endpoints()` — they carry
  the local Docker daemon's service data.

### 10. PVE_ENV must take precedence over TF_VAR_proxmox_node in the teardown script

- `TARGET_NODE_EXPECTED` was derived from `TF_VAR_proxmox_node` before `PVE_ENV`.
- `TF_VAR_proxmox_node` may be set to a stale value in the shell from a prior
  session (e.g. `pve-test` when running against `pve-test-vm`).
- `PVE_ENV` is the explicit user intent. It should win over the ambient env var.
- Fixed in `scripts/teardown-deploy-test.sh` line 24 (commits `fe9868d`, `a8bab1d`).

### 11. Ansible play vars are scoped per-play

- A `vars:` block defined in one play is not visible in other plays in the same
  playbook — even in the same file. Ansible play vars do not cross play boundaries.
- If a variable is needed in multiple plays, declare it in each play's `vars:` block
  or use `set_fact` with a persistent scope.
- This caused `netbox_network_env` to be undefined in the timer-install play despite
  being declared in the provision play (fixed in `5df61f0`).

## Suggested Use

- Read this document before planning the next teardown/redeploy rehearsal.
- Prefer updating this file when a new cycle teaches a reusable operational
  lesson.
- Keep raw evidence under stamped directories, but summarize durable takeaways
  here or in tracked closeout reports.
