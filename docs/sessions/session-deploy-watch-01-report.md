# Session deploy-watch-01 Report

- Session ID: deploy-watch-01
- Date: 2026-05-02
- Branch: work/portainer-oidc-runtime-fix-06
- Baseline SHA: 64fd1fce123062329ef5815d863d262e0b86a3a2
- Runtime validated SHA: c5260bff8892d678c0e4f5750824a35b6c94ad91
- Delta type: runtime-change
- Issue context: #188

## Executive Summary

Completed full deploy-watch sequence on pve-test for all 10 infrastructure stacks in dependency order. All stack apply/provision/smoke gates passed. `activate-edge` completed successfully with post-activate reconcile dry-run clean. Final platform status shows all stacks healthy and running.

During source-preflight, one unit test failed due to environment coupling (`AUTHENTIK_EXTRA_CA`) when running under `with-secrets`. Opened and closed issue #189 after applying and validating a test isolation fix (commit c5260bf).

## Gate Results

1. guard-target: PASS
2. source-preflight: PASS (after fix in c5260bf)
3. deploy-apt-cacher-stack: PASS
4. deploy-harbor-stack: PASS
5. deploy-ci-runner-01: PASS
6. deploy-dns-stack: PASS
7. deploy-step-ca-stack: PASS
8. deploy-proxy-stack: PASS
9. deploy-authentik-stack: PASS
10. activate-edge: PASS
11. deploy-monitoring-stack: PASS
12. deploy-netbox-stack: PASS
13. deploy-portainer-stack: PASS
14. platform-status-final: PASS
15. timing-summary: PASS

## Per-Gate Evidence Mapping

- guard-target
  - evidence_path: docs/sessions/evidence/deploy-watch-01/platform-status-final.log
- source-preflight
  - evidence_path: docs/sessions/evidence/deploy-watch-01/source-preflight.log
- deploy-apt-cacher-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-apt-cacher-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-apt-cacher-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-apt-cacher-stack.log
- deploy-harbor-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-harbor-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-harbor-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-harbor-stack.log
- deploy-ci-runner-01
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-ci-runner-01.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-ci-runner-01.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-ci-runner-01.log
- deploy-dns-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-dns-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-dns-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-dns-stack.log
- deploy-step-ca-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-step-ca-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-step-ca-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-step-ca-stack.log
- deploy-proxy-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-proxy-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-proxy-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-proxy-stack.log
- deploy-authentik-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-authentik-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-authentik-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-authentik-stack.log
- activate-edge
  - evidence_path: docs/sessions/evidence/deploy-watch-01/activate-edge.log
- deploy-monitoring-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-monitoring-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-monitoring-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-monitoring-stack.log
- deploy-netbox-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-netbox-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-netbox-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-netbox-stack.log
- deploy-portainer-stack
  - evidence_path: docs/sessions/evidence/deploy-watch-01/apply-portainer-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/provision-portainer-stack.log
  - evidence_path: docs/sessions/evidence/deploy-watch-01/smoke-portainer-stack.log
- platform-status-final
  - evidence_path: docs/sessions/evidence/deploy-watch-01/platform-status-final.log
- timing-summary
  - evidence_path: docs/sessions/evidence/deploy-watch-01/timing.log

## Per-Stack Timing and Health

- apt-cacher-stack: 92s, healthy, smoke `http://10.57.3.11:3142/` -> 406
- harbor-stack: 287s, healthy, smoke `http://10.57.3.10/v2/` -> 401
- ci-runner-01: 169s, healthy, actions runner service running in VMID 141
- dns-stack: 125s, healthy, DNS `traefik.lab.gibbsgreatly.xyz` -> 10.57.2.10
- step-ca-stack: 109s, healthy, ACME directory reachable
- proxy-stack: 138s, healthy, Traefik HTTPS responds (HTTP/2 404 expected pre-routes)
- authentik-stack: 389s, healthy, live health endpoint reachable
- monitoring-stack: 266s, healthy, Grafana login and VictoriaMetrics ready
- netbox-stack: 712s, healthy, HTTP status 302
- portainer-stack: 190s, healthy, `/api/system/status` responds

Total measured deploy time (sum): 2477s (~41m 17s)

## Warning Signs / Notable Observations

- First apt-cacher gate attempt used `./with-secrets` from inside stack directory and failed path resolution. Re-ran with absolute path (`/home/steve/git/proxmox-homelab/with-secrets`) and succeeded.
- `docs/sessions/evidence/deploy-watch-01/timing.log` contains one stale entry: `DURATION apt-cacher-stack 0s` from the failed first attempt, followed by the valid `92s` entry.
- Some smoke log files created through piped commands are empty even when gate command exited 0; direct follow-up checks confirmed endpoint health.

## Development Work Triggered

- Issue opened: #189
  - Title: fix: test_default_client_verifies_tls fails when AUTHENTIK_EXTRA_CA is set in environment
  - Root cause: test depended on absent `AUTHENTIK_EXTRA_CA`, but `with-secrets` sets it.
  - Fix: patch test with `mock.patch.dict(os.environ, {"AUTHENTIK_EXTRA_CA": ""})` for isolation.
  - Commit: c5260bf
  - Issue closed after verified fix.

## Evidence

Primary evidence directories:

- docs/sessions/evidence/deploy-watch-01/
- docs/teardown-test/evidence/deploy-watch-01/

Key logs:

- source-preflight: docs/sessions/evidence/deploy-watch-01/source-preflight.log
- gate logs (apply/provision/smoke): docs/sessions/evidence/deploy-watch-01/
- activate-edge: docs/sessions/evidence/deploy-watch-01/activate-edge.log
- platform status final: docs/sessions/evidence/deploy-watch-01/platform-status-final.log
- platform status machine outputs:
  - docs/teardown-test/evidence/deploy-watch-01/logs/platform-status.tsv
  - docs/teardown-test/evidence/deploy-watch-01/logs/platform-status.json
- timing summary: docs/sessions/evidence/deploy-watch-01/timing.log

## Final State

- pve-test target guard: verified
- All 10 stacks: running and healthy
- Edge activation: applied and reconciled
- Working tree: clean
- HEAD: c5260bff8892d678c0e4f5750824a35b6c94ad91
