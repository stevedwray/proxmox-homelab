# Session Report: deploy-kickoff-evening-01

## 1. Session Metadata

| Field | Value |
|---|---|
| Session ID | deploy-kickoff-evening-01 |
| Branch | work/teardown-validate-post-netbox-sso-01 |
| HEAD SHA | 23b7944113ddd8f1104db7d86733d9a471b0d6c4 |
| Baseline anchor | 028d37798cd8c633de43ffcefb84e5f1d7656dc7 |
| Runtime validated SHA | 23b7944113ddd8f1104db7d86733d9a471b0d6c4 |
| Delta type (`none` / `metadata-only` / `runtime-change`) | none |
| Lineage check | PASS |
| Target guard | PASS |
| Working tree | clean |
| Open issues at start | none |

## 2. Gate Results

### `guard-target` - PASS

```bash
$ cd /home/steve/git/proxmox-homelab && ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
pve-test
exit: 0
```

### `deploy-cycle` - FAIL

```bash
$ cd /home/steve/git/proxmox-homelab && ./with-secrets bash scripts/teardown-deploy-test.sh cycle --stamp 20260502-evening-deploy-01 --execute --approval-text 'I approve pve-test teardown deploy test op-06 destroy; op-07 through op-16 stop on first failure; does not authorize rebuild apply or edge publish op-25 op-28 op-29 reconcile apply' --approval-packet .git/ai/session-deploy-kickoff-evening-01.approval.yaml
...
[2026-05-02T07:17:29Z] FAIL provision-harbor-stack: /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-evening-deploy-01/logs/provision-harbor-stack.log
exit status 2
```

Failure context (from failing step log):

```text
AKD100: failed to query Authentik read-only endpoints: <urlopen error [Errno 113] No route to host>
```

Last successful phase before failure: `deploy-harbor-stack`.

### `post-cycle-op28` - SKIP

```bash
$ cd /home/steve/git/proxmox-homelab && ./with-secrets bash scripts/check-monitoring-stack.sh
skipped because deploy-cycle failed before reaching post-cycle validation gate
exit: not-run
```

## 3. Changes Made

- Runtime evidence and logs created under `docs/teardown-test/evidence/20260502-evening-deploy-01/`.
- Timing summary generated at `docs/teardown-test/evidence/20260502-evening-deploy-01/logs/duration-report.md`.
- Session report created at `docs/sessions/session-deploy-kickoff-evening-01-report.md`.
- No source code changes were made.

## 4. Blockers

- Harbor provisioning failed during OIDC reconciliation to Authentik.
- Why it blocks: `deploy-cycle` cannot proceed to edge activation/platform/final validation while `provision-harbor-stack` fails.
- Exact failing command: `./with-secrets /home/steve/git/proxmox-homelab/scripts/provision.sh --stack harbor-stack` (invoked by harness).
- Log path: `docs/teardown-test/evidence/20260502-evening-deploy-01/logs/provision-harbor-stack.log`.
- Last successful phase: `deploy-harbor-stack`.

## 5. Recommendation

Architect should focus on resolving Harbor-to-Authentik reachability/OIDC bootstrap (AKD100 no-route-to-host) and then resume the run from Harbor provision onward in the same evidence stamp.
