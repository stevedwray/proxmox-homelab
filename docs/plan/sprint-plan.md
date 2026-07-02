# Sprint Plan — Post-Multi-Source Inventory Merge

> Historical sprint snapshot.
> This document captures a bounded June 2026 work plan and still references the
> retired `baseline/teardown-validated` and `dev/pve-test` branch model.
> It should not be used as the source of truth for current workflow rules.
> Use [README.md](README.md), [docs/workflow/branch-model.md](../workflow/branch-model.md),
> and [docs/workflow/environments.md](../workflow/environments.md) for the
> current model.

**Sprint start:** 2026-06-13, `baseline/teardown-validated` @ `b7e20ba`
**Sprint scope:** CI hygiene, TLS hardening, step-ca metrics, monitoring
  enhancements, harness improvements, NetBox static hosts.
**Out of scope:** Phase 06 app migration, pve production parity, broad
  docker-socket-proxy rollout.

See [current-state.md](current-state.md) for the authoritative resume point.
This document describes session boundaries, handoff state, and promotion gates.

---

## Session 1 — `fix/ci-pipeline-cleanup`

**Branch:** `fix/ci-pipeline-cleanup` from `baseline/teardown-validated`
**Live infra required:** No
**Promotion gate:** CI passes on the branch (no teardown)

### Pre-session check

Verify Harbor has a proxy cache configured for `ghcr.io` before changing
the Authentik compose image references:

```bash
# In Harbor UI: Administration → Registries
# Confirm an endpoint named "ghcr-io" (or similar) exists for https://ghcr.io
# If not: create the registry endpoint, then create a proxy cache project.
```

### Tasks

**1a — Remove `dev/pve-test` from workflow triggers**

Files and lines:

| File | Section |
|---|---|
| `.github/workflows/validate.yml` | `push.branches` and `pull_request.branches` |
| `.github/workflows/security-scan.yml` | `push.branches` and `pull_request.branches` |
| `.github/workflows/supply-chain-signing-proof.yml` | `push.branches` |

Replace `dev/pve-test` entries with `baseline/teardown-validated` in each.

**1b — Fix ShellCheck false positives**

Add targeted inline `# shellcheck disable=` directives. Do not suppress
globally at file level unless the pattern is pervasive throughout the file.

| Script | Lines | Rule | Reason |
|---|---|---|---|
| `scripts/rebuild-gate-destroy.sh` | 88 | SC2015 | intentional `&& \|\| true` pattern |
| `scripts/plan-pve-infra-teardown.sh` | 477–595 | SC2016 | intentional single-quoted `bash -c '...'` args |
| `scripts/merge-sops-env.sh` | 29, 33 | SC1090 | dynamic source path |
| `scripts/run-netbox-populate-container.sh` | 20, 22 | SC1090 | dynamic source path |
| `scripts/check-proxmox-status.sh` | 198 | SC2034 | `depends_on`/`playbook` used externally |
| `scripts/preflight-network-refactor.sh` | 44 | SC2034 | same |
| `scripts/deploy-phase-04.sh` | 79 | SC2034 | same |
| `scripts/deploy-phase-04-orchestrate.sh` | 128 | SC2034 | same |
| `router/scripts/cutover.sh` | 25, 86 | SC2016 | intentional single-quoted args |

**1c — Fix Harbor image policy failures in authentik-stack compose**

File: `terraform/lxc/stacks/authentik-stack/docker-compose.yml` lines 30, 56, 67.

These are the deployed image references (used directly via `lookup('file', ...)`
in the Authentik playbook). Change:

| Current | Replacement |
|---|---|
| `ghcr.io/goauthentik/server:2024.12.3` | `harbor.lab.gibbsgreatly.xyz/ghcr-io/goauthentik/server:2024.12.3` |
| `docker.io/library/nginx:1.27-alpine` | `harbor.lab.gibbsgreatly.xyz/dockerhub/library/nginx:1.27-alpine` |

Pre-condition: Harbor `ghcr-io` proxy cache project must exist before this
change can be validated on a cold deploy. Confirm before merging.

**1d — Ansible lint CI failure**

Check whether the CI job uses a different profile or `.ansible-lint` config
that treats `yaml[line-length]` as fatal. If so, either add a `line-length`
exception to `.ansible-lint` or adjust the profile to match local behaviour.

### Handoff state

- All four sub-items complete, CI green on branch
- Branch merged to `baseline/teardown-validated`
- Confirm Harbor `ghcr-io` proxy cache exists (or note its absence as a
  blocker for 1c validation on next teardown)

---

## Session 2 — `fix/tls-hardening`

**Branch:** `fix/tls-hardening` from `baseline/teardown-validated`
**Live infra required:** Yes — pve-test-vm must be up
**Promotion gate:** Live Authentik SSO login on Harbor + at least one of
  Grafana or Portainer after redeploy of proxy-stack and harbor-stack

### Tasks

**2a — Traefik forward-auth: replace `insecureSkipVerify` with CA**

File: `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`

```yaml
# Before (around line 165):
tls:
  insecureSkipVerify: true

# After:
tls:
  ca: /certs/combined-ca.crt
```

The combined CA bundle (`/certs/combined-ca.crt`) is built conditionally in
the playbook from the system CA store + `homelab-root.crt` if it exists.
Run `deploy-proxy-stack.yml` after the change. Verify: Grafana/Portainer
still authenticate through Authentik forward-auth.

**2b — Harbor OIDC: enable cert verification**

File: `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`

Change the `harbor_postconfigure_oidc_verify_cert` default from `'false'` to
`'true'`. Harbor's OIDC endpoint is the public Authentik URL via Traefik with
a Let's Encrypt cert; Harbor trusts LE by default. No cert config changes
needed.

```yaml
# Before (around line 80):
harbor_postconfigure_oidc_verify_cert: "{{ lookup('env', 'HARBOR_OIDC_VERIFY_CERT') | default('false', true) | bool }}"

# After:
harbor_postconfigure_oidc_verify_cert: "{{ lookup('env', 'HARBOR_OIDC_VERIFY_CERT') | default('true', true) | bool }}"
```

Run `deploy-harbor-stack.yml` after the change. Verify: Harbor UI SSO via
the Authentik button completes successfully.

### Handoff state

- Proxy-stack redeploy completed with CA cert in forwardAuth
- Harbor-stack redeploy completed with OIDC verify enabled
- Live SSO test passed on Harbor + Grafana (or Portainer)
- Branch merged to `baseline/teardown-validated`

---

## Session 3 — `feat/step-ca-metrics` + monitoring enhancements

**Branch:** `feat/step-ca-metrics` from `baseline/teardown-validated`
**Live infra required:** Yes — pve-test-vm must be up
**Promotion gate:** step-ca scrape target shows `UP` in Grafana
  (Status → Targets → job=step-ca)

### Tasks

**3a — Mount homelab CA into VictoriaMetrics**

File: `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`

In the VictoriaMetrics service definition within the compose block, add a
volume:

```yaml
volumes:
  - /usr/local/share/ca-certificates/homelab-root.crt:/etc/ssl/certs/homelab-root.crt:ro
  # (keep existing volumes)
```

**3b — Add step-ca scrape job**

In the inline VictoriaMetrics scrape config (written via `ansible.builtin.copy`),
add a job after the existing jobs:

```yaml
- job_name: step-ca
  scheme: https
  tls_config:
    ca_file: /etc/ssl/certs/homelab-root.crt
  static_configs:
    - targets: ["{{ lookup('env', 'LAB_IP_STEP_CA') }}:9443"]
      labels:
        stack: step-ca-stack
```

**3c — Loki retention**

File: `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` (Loki
config block).

Add a `compactor` block to the Loki config:

```yaml
compactor:
  working_directory: /loki/compactor
  shared_store: filesystem
  retention_enabled: true

limits_config:
  retention_period: 30d
```

**3d — Authentik metrics dashboard**

Authentik exposes Prometheus metrics on the `/metrics` endpoint (authenticated).
Either:
- Add a VictoriaMetrics scrape job for `authentik-stack` (requires service
  account or token)
- Import the community Grafana dashboard for Authentik

If the scrape endpoint requires authentication, note the credential path in
`secrets.enc.yaml` and defer to a follow-up if access is unclear.

### Handoff state

- `deploy-monitoring-stack.yml` applied; step-ca target shows `UP` in Grafana
- Loki retention configured; `compactor` running
- Authentik dashboard: either imported or deferred with explicit note
- Branch merged to `baseline/teardown-validated`

---

## Session 4 — Harness validation improvements + provision.sh fix

**Branch:** `fix/harness-validation` from `baseline/teardown-validated`
**Live infra required:** No (source-only changes; full cycle run recommended
  but not required for promotion)
**Promotion gate:** `source-preflight` and `plan` pass cleanly; no teardown
  gate required for harness-only changes

### Tasks

**4a — Fix `provision.sh` APPROVED_PLATFORM_ORDER gap**

The `test-storage` and `test-storage-extra` stacks have `deployment_tier:
platform` in their `stack.yaml` but are absent from `APPROVED_PLATFORM_ORDER`
in `scripts/provision.sh`. Running `--tier platform` will skip them silently
or fail. Either:
- Add them to `APPROVED_PLATFORM_ORDER` if they should be deployable via
  `--tier platform`, or
- Change their `deployment_tier` to a non-platform value if they are
  test-only disposable stacks

Confirm intent before changing.

**4b — Strengthen final-validation assertions**

File: `scripts/teardown-deploy-test.sh` — `phase_final_validation()`.

Add explicit assertion functions that check observed values rather than just
exit codes:

- DNS: assert `dig` answer equals `${LAB_IP_PROXY}` for each browser FQDN
  (already partly done via `run_dns_answer_check`; verify it's wired for all
  `BROWSER_HOSTS`)
- Harbor `/v2/`: assert HTTP 401 (registry auth challenge), not a redirect
  to Authentik (which would indicate the forward-auth middleware is
  incorrectly applied to Harbor)
- Portainer: assert HTTP 200 from
  `http://${LAB_IP_PORTAINER}:9000/api/system/status`
- Final reconcile dry-run: assert the output contains no `issues` and no
  `writes` (parse JSON output)

**4c — Evidence summary generation**

After each phase completes, write a `summary.md` under the evidence stamp
directory summarising: branch, commit, phase results, log paths, and any
deviations. Keep it secrets-clean (no credentials in output).

The summary should be safe to copy into a tracked teardown summary doc if one
is still needed
without scrubbing.

### Handoff state

- `provision.sh` gap resolved (stacks correctly classified)
- `final-validation` asserts specific HTTP status codes and DNS answers
- Evidence summary written per phase
- `source-preflight` and `plan` pass on branch
- Branch merged to `baseline/teardown-validated`
- Note whether a full validation cycle was run to exercise new assertions

---

## Session 5 — Harness self-tests + NetBox static hosts

**Branch:** `fix/harness-tests-and-netbox` from `baseline/teardown-validated`
**Live infra required:** No for harness tests; pve-test-vm needed for NetBox
  populate verification
**Promotion gate:** Harness tests pass without network access; NetBox
  populate runs cleanly with expected object counts

### Tasks

**5a — Harness self-tests (Bats)**

Add Bats shell tests covering the safety-critical harness behaviours:

| Test | What it verifies |
|---|---|
| `--help` is side-effect free | No files written, no network calls |
| Missing `--approval-text` fails before live commands | Error before any guard or network call |
| Mutating phase without `--execute` fails | Refuses before target guard |
| Approval phrase matching is case-insensitive | `Approve`, `APPROVE` all accepted |
| `--stamp` routes logs to correct directory | Evidence written to `EVIDENCE_ROOT/<stamp>/` |
| Inventory VMID/IP mismatch fails `plan` | Synthetic mismatch triggers clean error |

Use mocks for `with-secrets`, `terragrunt`, `ssh`, `curl`, `dig` so tests
run without network or Proxmox access.

Test file: `tests/teardown-harness.bats` (or `scripts/test/`).

**5b — Harness concurrency lock**

Add a lock file under the evidence root when a destructive phase starts;
remove it on clean exit or document its path for manual removal on stale lock.
Include: evidence stamp, PID, branch, commit.

**5c — NetBox static hosts**

File: `terraform/lxc/stacks/netbox-stack/pve-test-vm.yaml` (or equivalent
network intent YAML for pve-test-vm).

Add entries to `static_hosts:` for:
- Linux desktop (IP to be confirmed by operator)
- Raspberry Pi (IP to be confirmed by operator)
- Any other non-Proxmox hosts with known stable IPs

Run populate and verify objects appear in NetBox with correct IPs.

**5d — Stale IP investigation**

The IP `192.168.1.41/24` (pve-test-vm hypervisor host) appears as a stale
managed object in NetBox. Investigate:
- Should it be registered as a device IP (the Proxmox host itself) rather
  than a VM IP?
- Or should it be suppressed from the stale-object check?

Resolve and confirm a clean populate run reports no unexpected stale objects.

### Handoff state

- Bats tests present in `tests/` or `scripts/test/`, passing without network
- Lock file logic in place
- NetBox static hosts populated (or deferred with explicit note on what IPs
  are still unknown)
- Stale IP resolved
- Branch merged to `baseline/teardown-validated`

---

## Deferred to future sprint

The following are out of scope for this sprint and should not be started
until the sessions above are complete:

| Item | Trigger to start |
|---|---|
| Phase 06 app discovery (#113) | Sessions 1–5 complete; pve-test-vm stable |
| Phase 06 migrations: Pi-hole, arr, Jellyfin, game (#114–#118) | Discovery complete |
| Harness reporting: tracked report skeleton | Session 4 summary.md done; evaluate if more needed |
| pve production parity | Separate promotion gate; not this sprint |
| Broad docker-socket-proxy rollout | Separate workstream |
| Traefik → Harbor backend HTTPS | Deferred: acceptable posture |
| Harbor OIDC internal direct endpoint | Deferred: discovery-coupled complexity |

---

## Session order dependencies

```
Session 1 (CI cleanup)        ← no dependencies; run first
    ↓ merge
Session 2 (TLS hardening)     ← needs live pve-test-vm
    ↓ merge
Session 3 (step-ca metrics)   ← needs live pve-test-vm; can overlap with Session 2
    ↓ merge
Session 4 (harness + fix)     ← no live infra; can start after Session 1
    ↓ merge
Session 5 (tests + NetBox)    ← harness tests after Session 4; NetBox needs live infra
    ↓ merge
Phase 06 prep (future)
```

Sessions 2 and 3 both require a deployment window on pve-test-vm and can be
done back-to-back in the same window if desired. Sessions 4 and 5 are
primarily code work and can be done independently of the live-infra sessions.
