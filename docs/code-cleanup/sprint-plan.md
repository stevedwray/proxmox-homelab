# Code Cleanup Sprint Plan

**Sprint start:** 2026-06-14, `baseline/teardown-validated` @ `c4c38d8`
**Scope:** SonarCloud hotspot suppression, bandit/ruff fixes, cognitive
  complexity reduction.
**Prerequisite:** PR #358 (`fix/ci-pipeline-cleanup`) must merge first —
  it adds the `python-lint` CI job that gates sessions CC-1 and CC-2.

## Sprint status (updated 2026-06-14)

| Session | Status | Branch / PR | Notes |
|---|---|---|---|
| CC-1 | **Done** | `fix/sonar-suppressions` / PR #366 | #362 #363 closed 2026-06-15 |
| CC-2 | **Done** | — | #355 #356 #357 #361 closed |
| CC-3 | **Done** | `fix/cognitive-complexity-cc5` / PR #370 | #359 closed |
| CC-4 | **Done** | `fix/cognitive-complexity-cc5` / PR #370 | #364 closed |
| CC-5 | **Done** | `fix/cognitive-complexity-cc5` / PR #370 | #365 closed |

**`baseline/teardown-validated` is at `009e2b3` (teardown-validated 2026-06-14).**

**All code-cleanup issues closed. Sprint complete.**

See [findings.md](findings.md) for full classification rationale.
See [docs/plan/sprint-plan.md](../plan/sprint-plan.md) for the main
infrastructure sprint; CC-3 is absorbed into that sprint's Session 2.

---

## Session CC-1 — Suppressions and one-line fixes

**Branch:** `fix/sonar-suppressions` from `baseline/teardown-validated`
**Live infra required:** No
**Promotion gate:** SonarCloud `TO_REVIEW` hotspot count reduced by ≥ 90
  (from 101 to ≤ 11); `python-lint` CI job green; quality gate remains PASS

### Pre-session check

Confirm PR #358 is merged before starting — the `python-lint` job must
exist in CI for the gate to be meaningful.

### Tasks

**CC-1a — Suppress Docker-internal compose URLs** (FP1)

Add `# nosonar: ansible:S5332` to each flagged line with a brief note.
Target lines in:
- `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`: lines 84, 273
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`: lines 348, 385, 391, 396

Comment form:
```yaml
- url: http://loki:3100/loki/api/v1/push  # nosonar: ansible:S5332 — Docker-internal hostname, never reaches SDN
```

Resolves part of [#360](https://github.com/stevedwray/proxmox-homelab/issues/360).

---

**CC-1b — Accept and suppress Portainer, Grafana, NetBox admin API calls** (FP2)

Add `# nosonar: ansible:S5332` to each flagged line with rationale note.
Target files:
- `deploy-portainer-stack.yml`: lines 104, 210, 218, 249, 259, 272, 285, 303
- `deploy-monitoring-stack.yml`: lines 107, 337, 374, 380, 652, 663, 674, 685, 713, 724–782
- `deploy-netbox-stack.yml`: line 63

Comment form:
```yaml
url: "http://{{ ansible_host }}:9000/api/system/status"  # nosonar: ansible:S5332 — Portainer CE has no HTTPS management port; private SDN only
```

Resolves part of [#360](https://github.com/stevedwray/proxmox-homelab/issues/360).

---

**CC-1c — Suppress teardown harness health-check curls** (FP3)

Add `# NOSONAR` to unauthenticated health-check `curl` calls in:
- `scripts/teardown-deploy-test.sh`: lines 1436, 1439, 1443, 1461, 1517, 1527, 1538, 1592, 1602, 1613, 2063
- `scripts/test-docker-mount-resize.sh`: lines 135, 138, 141, 144, 147

Comment form:
```bash
curl -fsS "http://${ip}:9000/-/health/live/"  # NOSONAR — unauthenticated health check on private SDN
```

Resolves part of [#360](https://github.com/stevedwray/proxmox-homelab/issues/360).

---

**CC-1d — Add fixture directory to sonar.exclusions** (FP4)

File: `sonar-project.properties`

```properties
sonar.exclusions=...,docs/provisioning-refactor/fixtures/**
```

Removes 12 `kubernetes:S5332` false positives on test fixture YAML files.

Resolves part of [#360](https://github.com/stevedwray/proxmox-homelab/issues/360).

---

**CC-1e — Suppress Prometheus listener and NetBox client HTTP** (FP5, FP6)

```python
# harbor_findings_exporter.py:498
listen_address = _env("HARBOR_FINDINGS_LISTEN_ADDRESS", "0.0.0.0")  # nosonar: python:S5332 — Prometheus exporter; HTTP metrics listener is standard

# client.py:19
f"http://{os.environ.get('LAB_IP_NETBOX')}:8080"  # nosonar: python:S5332 — NetBox HTTP-only on private SDN; accepted risk per findings.md FP6
```

Resolves part of [#360](https://github.com/stevedwray/proxmox-homelab/issues/360).

---

**CC-1f — Add non-root USER to netbox-stack Dockerfile** (S4)

File: `terraform/lxc/stacks/netbox-stack/integrations/Dockerfile`

```dockerfile
RUN useradd --system --no-create-home appuser
USER appuser
```

Add before the `ENTRYPOINT`. Verify the populate container still runs
(`scripts/run-netbox-populate-container.sh`) — the entrypoint must not
require write access to paths owned by root.

Closes [#362](https://github.com/stevedwray/proxmox-homelab/issues/362).

---

**CC-1g — Suppress shell:S6506 in setup-dev-env.sh** (FP7)

File: `scripts/setup-dev-env.sh:61`

```bash
TERRAFORM_VERSION=$(curl -s https://api.github.com/repos/hashicorp/terraform/releases/latest | ...)  # nosonar: shell:S6506 — redirect follow required for GitHub release CDN
```

Closes [#363](https://github.com/stevedwray/proxmox-homelab/issues/363).

---

**CC-1h — Update positive Harbor image policy check** (follow-up from #357)

File: `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` also references
`ghcr.io/goauthentik/server` in the compose file (tracked in sprint plan 1c).
This item is about adding a positive regex to the `harbor-image-policy` CI job
to check all compose image references use `harbor.lab.gibbsgreatly.xyz/...`.

Closes [#357](https://github.com/stevedwray/proxmox-homelab/issues/357).

### Handoff state

- All suppression comments in place; SonarCloud hotspot count ≤ 11
- `docker:S6471` resolved (non-root user in Dockerfile)
- `sonar.exclusions` updated for fixture files
- `shell:S6506` suppressed
- Branch merged to `baseline/teardown-validated`
- Remaining open hotspots: Authentik authenticated API calls (#359),
  ReDoS regex (#361), any docker:S6471 recurrence

---

## Session CC-2 — Python security and lint fixes

**Branch:** `fix/python-security-lint` from `baseline/teardown-validated`
**Live infra required:** No
**Promotion gate:** `python-lint` CI job passes green (zero ruff + bandit
  findings); no new SonarCloud security hotspots introduced

### Prerequisite

PR #358 must be merged. The `python-lint` CI job added in that PR is the
gate for this session.

### Tasks

**CC-2a — Fix ruff auto-fixable warnings** (CQ1 — F401, F841)

Run `ruff check --fix` on all project Python files, then review the diff:

```bash
find . -name '*.py' \
  -not -path './.git/*' \
  -not -path './_legacy/*' \
  -not -path '*/.terragrunt-cache/*' \
  -not -path './.venv/*' \
  | xargs ruff check --fix
```

Expected auto-fixes (14 items):
- Remove unused imports: `datetime.timezone`, `sys`, `re`, `subprocess`,
  `pprint` (×2), `unittest.mock.call`, `unittest.mock.patch`, `os`,
  `io`, `urllib.error`, `urllib.request`, `typing.Tuple`
- Remove unused variable: `manifests` in `harbor_scan_smoke.py:394`

Resolves part of [#356](https://github.com/stevedwray/proxmox-homelab/issues/356).

---

**CC-2b — Fix E402 import-not-at-top** (CQ1 — E402)

These are intentional `sys.path.insert()` + local import patterns in
scripts that need to add the script directory before importing. Add
`# noqa: E402` to the import line in each case:

| File | Line | Import |
|---|---|---|
| `terraform/lxc/discover-authentik-edge.py` | 21 | `from edge_manifest import ...` |
| `terraform/lxc/reconcile-edge.py` | 24 | `from edge_manifest import ...` |
| `terraform/lxc/render-edge-coredns.py` | 20 | `from edge_manifest import ...` |
| `scripts/preflight-production-mikrotik.py` | 20 | `from mikrotik_client import ...` |
| `terraform/lxc/test_reconcile_authentik_edge.py` | 18 | `import os` (after module injection) |
| `terraform/lxc/test_reconcile_edge.py` | 22 | `import os` (after module injection) |

Resolves part of [#356](https://github.com/stevedwray/proxmox-homelab/issues/356).

---

**CC-2c — Fix E731 lambda assignments** (CQ1 — E731)

File: `terraform/lxc/stacks/netbox-stack/configuration/configuration.py` lines 40–42

```python
# Before:
_AS_BOOL = lambda value: value.lower() == 'true'
_AS_INT = lambda value: int(value)
_AS_LIST = lambda value: list(filter(None, value.split(' ')))

# After:
def _AS_BOOL(value): return value.lower() == 'true'
def _AS_INT(value): return int(value)
def _AS_LIST(value): return list(filter(None, value.split(' ')))
```

Note: this file is in `sonar.exclusions` (`netbox-stack/configuration/**`)
so SonarCloud won't see it, but ruff will. The fix is still correct.

Resolves part of [#356](https://github.com/stevedwray/proxmox-homelab/issues/356).
Closes [#356](https://github.com/stevedwray/proxmox-homelab/issues/356).

---

**CC-2d — Fix SSL verification bypass in Harbor tools** (S3)

File 1: `terraform/lxc/ansible/files/harbor_findings_exporter.py:72`

```python
# Before:
self._ssl_context = ssl._create_unverified_context()

# After:
_CA_PATH = "/usr/local/share/ca-certificates/homelab-root.crt"
self._ssl_context = (
    ssl.create_default_context(cafile=_CA_PATH)
    if os.path.exists(_CA_PATH)
    else ssl.create_default_context()
)
```

File 2: `terraform/lxc/ansible/roles/harbor_postconfigure/files/harbor_scan_smoke.py:49`

```python
# Before:
context = ssl._create_unverified_context() if insecure else None

# After:
_CA_PATH = "/usr/local/share/ca-certificates/homelab-root.crt"
if insecure:
    context = ssl._create_unverified_context()
else:
    context = ssl.create_default_context(cafile=_CA_PATH) if os.path.exists(_CA_PATH) else ssl.create_default_context()
```

The `os.path.exists` fallback ensures the scripts remain functional on
machines without the homelab CA (e.g. CI runners).

Closes [#355](https://github.com/stevedwray/proxmox-homelab/issues/355).

---

**CC-2e — Address ReDoS regex findings** (S2)

File 1: `terraform/lxc/ansible/roles/harbor_postconfigure/files/harbor_scan_smoke.py:86`

Add a length guard before the regex:
```python
def _parse_bearer_challenge(www_authenticate: str) -> dict[str, str]:
    if not www_authenticate.startswith("Bearer "):
        raise RuntimeError(f"Unsupported registry auth challenge: {www_authenticate}")
    if len(www_authenticate) > 4096:
        raise RuntimeError("WWW-Authenticate header exceeds safe length limit")
    pairs = dict(re.findall(r'([a-zA-Z_]+)="([^"]+)"', www_authenticate))
```

File 2: `terraform/lxc/edge_manifest.py:26`

Simplify or bound the pattern. The current pattern:
```python
r"^\{\{\s*[^}]*\|\s*default\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}$"
```

Rewrite to avoid the `\s*[^}]*` ambiguity:
```python
r"^\{\{\s*\S[^}]*\|\s*default\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}$"
```

(`\S` before `[^}]*` ensures at least one non-space before the pipe,
eliminating the `\s*[^}]*` overlap.)

Closes [#361](https://github.com/stevedwray/proxmox-homelab/issues/361).

### Handoff state

- `python-lint` CI job passes green (zero ruff + bandit findings)
- `bandit B323` resolved in both Harbor tool files
- ReDoS patterns bounded with length guards or simplified
- Branch merged to `baseline/teardown-validated`

---

## Session CC-3 — Authentik API HTTPS ✓ DONE

**Branch:** `fix/cognitive-complexity-cc5` / PR #370 (merged 2026-06-14)
**Originally planned as:** `fix/tls-hardening` (main sprint Session 2)
**Live infra required:** Yes — pve-test-vm must be up
**Promotion gate:** Authentik playbook redeploy succeeds; no `ansible:S5332`
  findings for credential-carrying API calls; Authentik SSO still works
  on Harbor and Grafana

See `docs/plan/sprint-plan.md` Session 2 for the full Traefik and Harbor
OIDC TLS work. This task is **added** to that session.

### Task CC-3a — Switch authenticated Ansible API calls to HTTPS:9443

File: `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`

Change the following `uri` module calls from HTTP:9000 to HTTPS:9443:
- Lines 468, 483, 515, 534, 546, 575 (all carry `Authorization: Bearer`)

```yaml
# Before:
url: "http://{{ ansible_host }}:9000/api/v3/core/users/..."
# (no validate_certs field)

# After:
url: "https://{{ ansible_host }}:9443/api/v3/core/users/..."
validate_certs: true
ca_path: /usr/local/share/ca-certificates/homelab-root.crt
```

Health-check calls at lines 407 and 418 (no credentials) can remain on
HTTP:9000 or move to HTTPS:9443 — move them for consistency.

After changing, redeploy `deploy-authentik-stack.yml` on pve-test-vm and
confirm all tasks succeed (the Authentik API must accept requests on 9443).

Closes [#359](https://github.com/stevedwray/proxmox-homelab/issues/359).

### Handoff state

- All `uri` module calls with credentials use `https://...:9443`
- Playbook redeploy tested on pve-test-vm — all tasks succeed
- `ansible:S5332` remaining in deploy-authentik-stack.yml are Docker-internal
  lines already suppressed in CC-1a
- This task merged as part of `fix/tls-hardening`

---

## Session CC-4 — NetBox cognitive complexity ✓ DONE

**Branch:** `fix/cognitive-complexity-cc5` / PR #370 (merged 2026-06-14)
**Originally planned as:** `fix/cognitive-complexity-netbox` from `baseline/teardown-validated`
**Live infra required:** No (unit tests provide the gate)
**Promotion gate:** All existing tests in `test_populate_paths.py`,
  `test_populate_multi_source.py`, `test_augment.py` pass; no function in
  `populate.py`, `discover.py`, `client.py` exceeds complexity 30

### Context

These files are the multi-source inventory engine added in
`feat/netbox-populate-multi-source-inventory`. They will be extended in
Phase 06 (app migration discovery). Reducing complexity now makes Phase 06
changes safer.

### Tasks

**CC-4a — Refactor `populate.py`** (complexity 118, 69, 29, 26, 18, 18)

`populate.py:1256` (complexity 118) is the main upsert loop. Extract:
- `_upsert_vm(client, vm, prefix_map) -> None`
- `_upsert_ip(client, vm, address, prefix) -> None`
- `_upsert_service(client, vm, service) -> None`

`populate.py:910` (complexity 69) is the IP reconciliation block. Extract:
- `_reconcile_ips(client, device, declared_ips) -> None`

The goal is to reduce each public function to ≤ 30 complexity by
delegating to focused private helpers.

---

**CC-4b — Refactor `discover.py`** (complexity 100, 29, 22, 19)

`discover.py:321` (complexity 100) is the main discovery loop. Extract
per-source discovery functions:
- `_discover_from_proxmox(client, node) -> list[VMRecord]`
- `_discover_from_mikrotik(client) -> list[VMRecord]`
- `_discover_from_portainer(client) -> list[VMRecord]`

---

**CC-4c — Refactor `client.py`** (complexity 44, 20)

`client.py:124` (complexity 44) is the NetBox API client's main upsert
helper. Extract per-object-type helpers following the same pattern as
`_upsert_vm`/`_upsert_ip` above.

### Handoff state

- All existing tests pass without modification
- No function in the three files exceeds complexity 30
- NetBox populate run on pve-test-vm produces same object counts (VMs: 26,
  IPs: 34, Services: 56) as the 2026-06-13 baseline
- SonarCloud `python:S3776` findings for these files resolved
- Branch merged to `baseline/teardown-validated`
- Closes [#364](https://github.com/stevedwray/proxmox-homelab/issues/364)

---

## Session CC-5 — Authentik reconciler and Harbor tooling complexity ✓ DONE

**Branch:** `fix/cognitive-complexity-cc5` / PR #370 (merged 2026-06-14)
**Originally planned as:** `fix/cognitive-complexity-reconciler` from `baseline/teardown-validated`
**Live infra required:** No (existing unit tests gate the reconciler;
  harbor tooling has no live dependency for the refactor itself)
**Promotion gate:** No function in the target files exceeds complexity 40
  (pragmatic target given the domain); existing tests pass

### Tasks

**CC-5a — Refactor `reconcile-authentik-edge.py:929`** (complexity 160)

The main reconciliation function. Extract:
- Provider reconciliation → `_reconcile_provider(session, manifest, state)`
- Application reconciliation → `_reconcile_application(session, manifest, state)`
- Policy binding reconciliation → `_reconcile_policy_bindings(session, ...)`

The function currently inlines all three concerns. Existing tests in
`test_reconcile_edge.py` and `test_reconcile_authentik_edge.py` provide
the regression guard.

---

**CC-5b — Refactor `harbor_findings_exporter.py:272`** (complexity 118)

Combine with the SSL fix from CC-2d (same file). The `collect()` method
inlines data fetching, filtering, and metric population. Extract:
- `_fetch_scan_results(project) -> list[dict]`
- `_filter_results(results, filters) -> list[dict]`
- `_emit_metrics(results, registry) -> None`

---

**CC-5c — Reduce complexity in `harbor_scan_smoke.py`** (complexity 56, 21)

The two functions at lines 273 and 336. Extract nested condition blocks
into named helpers (`_check_image_signatures`, `_verify_sbom`, etc.).

---

**CC-5d — Storage and stack validation scripts** (deferred sub-task)

`classify-storage-plan.py` (101), `validate-stack-metadata.py` (79),
`validate-storage-contract.py` (61): these have lower change frequency.
Address in a follow-up within this session if time allows, otherwise
create a chore issue.

### Handoff state

- `reconcile-authentik-edge.py:929` reduced to ≤ 40 complexity
- `harbor_findings_exporter.py:272` refactored (combined with CC-2d SSL fix)
- `harbor_scan_smoke.py` reduced to ≤ 25 complexity
- All existing reconciler and harbor tests pass
- Branch merged to `baseline/teardown-validated`
- Closes [#365](https://github.com/stevedwray/proxmox-homelab/issues/365)

---

## Session order and dependencies

```
PR #358 (fix/ci-pipeline-cleanup)   ← must merge first (adds python-lint job)
    ↓
Session CC-1 (fix/sonar-suppressions)     ← no live infra; run immediately
    ↓
Session CC-2 (fix/python-security-lint)   ← no live infra; gates on python-lint CI
    ↓
Session CC-3                              ← absorbed into main sprint Session 2
    (fix/tls-hardening)                     requires live pve-test-vm
    ↓
Session CC-4 (fix/cognitive-complexity-netbox)      ← no live infra; after CC-2
    ↓
Session CC-5 (fix/cognitive-complexity-reconciler)  ← no live infra; after CC-4
```

CC-1 and CC-2 can be batched into a single branch (`fix/sonar-and-lint`)
if preferred — they share the no-live-infra property and both need
PR #358 merged first.

CC-4 and CC-5 are independent refactors and can be done in parallel
branches if two sessions run concurrently.

---

## Deferred

| Item | Reason deferred |
|---|---|
| Grafana TLS on LXC | Requires cert rotation infrastructure; separate workstream |
| Portainer HTTPS management | Portainer Enterprise feature; not planned |
| Storage/stack validation scripts complexity | Low change frequency; address in CC-5d if time allows |
| `scripts/validate-*.py` complexity | Agent harness scripts; refactor only if schema changes required |
