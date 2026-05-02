# Session Report: teardown-validate-post-netbox-sso-01

## 1. Session Metadata

| Field | Value |
|---|---|
| Session ID | teardown-validate-post-netbox-sso-01 |
| Branch | work/teardown-validate-post-netbox-sso-01 |
| HEAD SHA | 1c6253aa48729837d0bbba03009418178c01c2d5 |
| Baseline anchor | 93fbb2d2396837487c75eab9f90937e0aeebca7e |
| Runtime validated SHA | 93fbb2d2396837487c75eab9f90937e0aeebca7e |
| Delta type (none / metadata-only / runtime-change) | none |
| Lineage check | PASS |
| Target guard | PASS |
| Working tree | dirty |
| Open issues at start | none |

Scan gate handling: `env.scan_gate=pr`, so security scans are deferred to PR and are not blockers for this session.

## 2. Gate Results

### guard - PASS

```bash
$ ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
pve-test
exit: 0
```

### live-preflight - PASS

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh live-preflight
[2026-05-02T05:13:02Z] evidence_dir=/home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302
[2026-05-02T05:13:02Z] working tree has local changes; see /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302/logs/git-status-short.log
[2026-05-02T05:13:02Z] branch=work/teardown-validate-post-netbox-sso-01
[2026-05-02T05:13:02Z] commit=1c6253aa48729837d0bbba03009418178c01c2d5
[2026-05-02T05:13:02Z] target guard passed: pve-test
[2026-05-02T05:13:02Z] START dns-authoritative-traefik: bash -lc dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz | grep -Fx '10.57.2.10'
[2026-05-02T05:13:02Z] PASS dns-authoritative-traefik: /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302/logs/dns-authoritative-traefik.log
[2026-05-02T05:13:02Z] START dns-delegated-traefik: bash -lc dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz | grep -Fx '10.57.2.10'
[2026-05-02T05:13:02Z] PASS dns-delegated-traefik: /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302/logs/dns-delegated-traefik.log
[2026-05-02T05:13:02Z] START https-route-traefik: bash -lc curl -skI --resolve traefik.lab.gibbsgreatly.xyz:443:10.57.2.10 https://traefik.lab.gibbsgreatly.xyz/ | grep -Eq '^HTTP/'
[2026-05-02T05:13:02Z] PASS https-route-traefik: /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302/logs/https-route-traefik.log
[2026-05-02T05:13:02Z] START authentik-direct-health: curl -fsS http://10.57.1.10:9000/-/health/live/
[2026-05-02T05:13:02Z] PASS authentik-direct-health: /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302/logs/authentik-direct-health.log
[2026-05-02T05:13:02Z] START reconcile-edge-dry-run: /home/steve/git/proxmox-homelab/with-secrets python3 /home/steve/git/proxmox-homelab/terraform/lxc/reconcile-edge.py --authentik-url http://10.57.1.10:9000 --no-verify-tls --json
[2026-05-02T05:13:04Z] PASS reconcile-edge-dry-run: /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302/logs/reconcile-edge-dry-run.log
[2026-05-02T05:13:04Z] DONE live-preflight; evidence_dir=/home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051302
exit: 0
```

### approval-preflight - FAIL

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh approval-preflight
[2026-05-02T05:13:07Z] evidence_dir=/home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051307
[2026-05-02T05:13:07Z] working tree has local changes; see /home/steve/git/proxmox-homelab/docs/teardown-test/evidence/20260502-051307/logs/git-status-short.log
[2026-05-02T05:13:07Z] branch=work/teardown-validate-post-netbox-sso-01
[2026-05-02T05:13:07Z] commit=1c6253aa48729837d0bbba03009418178c01c2d5
[2026-05-02T05:13:07Z] ERROR working tree is dirty
?? docs/sessions/evidence/
exit status 1
exit: 1
```

### destroy - SKIP

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh destroy --execute --approval-text 'teardown-validate-post-netbox-sso-01'
SKIPPED: not run because critical gate `approval-preflight` failed.
exit: N/A
```

### deploy-foundation - SKIP

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh deploy-foundation --execute --approval-text 'teardown-validate-post-netbox-sso-01'
SKIPPED: not run because critical gate `approval-preflight` failed.
exit: N/A
```

### deploy-edge - SKIP

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh deploy-edge --execute --approval-text 'teardown-validate-post-netbox-sso-01'
SKIPPED: not run because critical gate `approval-preflight` failed.
exit: N/A
```

### activate-edge - SKIP

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh activate-edge --execute --approval-text 'teardown-validate-post-netbox-sso-01'
SKIPPED: not run because critical gate `approval-preflight` failed.
exit: N/A
```

### deploy-platform - SKIP

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh deploy-platform --execute --approval-text 'teardown-validate-post-netbox-sso-01'
SKIPPED: not run because critical gate `approval-preflight` failed.
exit: N/A
```

### final-validation - SKIP

```bash
$ ./with-secrets bash scripts/teardown-deploy-test.sh final-validation
SKIPPED: not run because critical gate `approval-preflight` failed.
exit: N/A
```

### session-report - PASS

```bash
$ test -f docs/sessions/session-teardown-validate-post-netbox-sso-01-report.md
exit: 0
```

## 3. Changes Made

- docs/sessions/session-teardown-validate-post-netbox-sso-01-report.md: rewrote report with current gate evidence and stop condition. Commit SHA: pending.
- .git/ai/handoff-to-architect.yaml: will be rewritten to match this run and gate statuses. Commit SHA: pending.

## 4. Blockers

- approval-preflight failed because the working tree is not clean (`?? docs/sessions/evidence/`), which blocks all destructive/deploy gates by design.
- Remediation: clean or remove untracked files from `docs/sessions/evidence/` (or move them out of repo root), rerun `./with-secrets bash scripts/teardown-deploy-test.sh approval-preflight`, then resume gates from destroy onward in a new executor session.

## 5. Recommendation

Architect focus: resolve clean-tree precondition for approval-preflight first, then relaunch a continuation session for destroy through final-validation; this session advanced readiness evidence but did not progress runtime deployment gates.
