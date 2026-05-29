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

### 2. Use the direct Authentik URL for reconciler workflows

- The reconciler's default Authentik target produced discovery HTTP 404 during
  rehearsal flows.
- The stable working path during OP-25 and later validation was:

  ```bash
  ./with-secrets python3 terraform/lxc/reconcile-edge.py \
    --authentik-url http://${lab_ip_authentik}:9000 \
    --no-verify-tls
  ```

- Rehearsal and runbook commands should either use this direct URL explicitly
  or make the safe default unambiguous.

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

## Suggested Use

- Read this document before planning the next teardown/redeploy rehearsal.
- Prefer updating this file when a new cycle teaches a reusable operational
  lesson.
- Keep raw evidence under stamped directories, but summarize durable takeaways
  here or in tracked closeout reports.
