# Code Cleanup — Findings Classification

**Scan date:** 2026-06-14
**Tools:** SonarCloud (cloud analysis, every push), bandit 1.9.4, ruff 0.15.17 (local + CI)
**Scope:** All non-legacy Python, shell, Ansible, Terraform, Dockerfile.
  Excluded: `_legacy/`, `.terragrunt-cache/`, `.venv/`, `netbox-stack/configuration/`

---

## SDN topology reference

Understanding the network context is required to classify HTTP vs HTTPS
findings correctly. The architecture is:

```
Internet / Browser
    ↓ HTTPS (Let's Encrypt cert via Traefik)
proxy-stack (Traefik, 192.168.20.10)
    ↓ HTTP (internal forward)
authentik-stack  (192.168.20.10, port 9000 HTTP / 9443 HTTPS)
monitoring-stack (192.168.20.12, port 3000 Grafana / 8428 VictoriaMetrics)
portainer-stack  (192.168.20.20, port 9000 Portainer API)
harbor-stack     (192.168.40.10, port 80 HTTP)
netbox-stack     (192.168.40.12, port 8080 HTTP)
```

Ansible playbooks run from the control node and call these services
**directly** at their SDN IPs, bypassing Traefik. This means authenticated
API calls use the service's native port, which is HTTP for most services.

Docker compose-internal URLs (`http://loki:3100`, `http://victoriametrics:8428`)
resolve via Docker DNS only within the same compose network on the same
host — they never traverse the SDN.

---

## Security findings

### S1 — Authentik API calls with Bearer tokens over HTTP (REAL RISK)

**Rule:** `ansible:S5332`
**File:** `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`
**Lines:** 468, 483, 515, 534, 546, 575
**Issue:** [#359](https://github.com/stevedwray/proxmox-homelab/issues/359)
**Priority:** High

Ansible `uri` module calls to `http://{{ ansible_host }}:9000/api/v3/...`
carry `Authorization: Bearer` headers and (at line 515) a plaintext
password body. Unlike other services, **Authentik does expose HTTPS on port
9443**, making these HTTP calls fixable.

Lines 407 and 418 (health checks at `:9000/-/health/live/` and
`/-/health/ready/`) carry no credentials and can be assessed separately.

**Fix:** Change all authenticated calls to `https://{{ ansible_host }}:9443/api/v3/...`
with `validate_certs: true` and `ca_path` pointing to the homelab root CA
(`/usr/local/share/ca-certificates/homelab-root.crt`).

---

### S2 — ReDoS regex (REVIEW REQUIRED)

**Rule:** `python:S5852`
**Issue:** [#361](https://github.com/stevedwray/proxmox-homelab/issues/361)
**Priority:** Medium

| File | Line | Pattern | Input source |
|---|---|---|---|
| `terraform/lxc/ansible/roles/harbor_postconfigure/files/harbor_scan_smoke.py` | 86 | `r'([a-zA-Z_]+)="([^"]+)"'` | `WWW-Authenticate` HTTP response header from Harbor |
| `terraform/lxc/edge_manifest.py` | 26 | `r"^\{\{\s*[^}]*\|\s*default\(..."` | `stack.yaml` files from the repo |

`harbor_scan_smoke.py:86` processes a value from a network service response
and is the higher concern. A compromised or spoofed Harbor could send a
crafted header that causes catastrophic backtracking.

`edge_manifest.py:26` processes committed config files; risk is low but the
nested-quantifier pattern should be simplified.

---

### S3 — SSL certificate verification disabled (REAL RISK)

**Rule:** bandit B323 / CWE-295
**Issue:** [#355](https://github.com/stevedwray/proxmox-homelab/issues/355)
**Priority:** Medium

| File | Line | Pattern |
|---|---|---|
| `terraform/lxc/ansible/files/harbor_findings_exporter.py` | 72 | `ssl._create_unverified_context()` — always used |
| `terraform/lxc/ansible/roles/harbor_postconfigure/files/harbor_scan_smoke.py` | 49 | `ssl._create_unverified_context() if insecure else None` — conditional |

Both communicate with Harbor over HTTPS without verifying the server cert.
The homelab root CA is available on every LXC at
`/usr/local/share/ca-certificates/homelab-root.crt`. Fix is to use
`ssl.create_default_context(cafile=CA_PATH)` instead.

---

### S4 — Docker root user (ONE-LINE FIX)

**Rule:** `docker:S6471`
**File:** `terraform/lxc/stacks/netbox-stack/integrations/Dockerfile:1`
**Issue:** [#362](https://github.com/stevedwray/proxmox-homelab/issues/362)
**Priority:** Low

`python` base image runs as root. Add a `USER` instruction before the
entrypoint.

---

## False positives — suppress

### FP1 — Docker compose-internal URLs (NOT the SDN)

**Rule:** `ansible:S5332`
**Files:** `deploy-authentik-stack.yml` (lines 84, 273), `deploy-monitoring-stack.yml` (lines 348, 385, 391, 396)

URLs like `http://loki:3100`, `http://victoriametrics:8428`,
`http://harbor-findings-exporter:9414`, `proxy_pass http://server:9000`.
These are Docker DNS names that resolve only within the same compose
network — not the SDN. They are inert from a network security perspective.

**Action:** Add `# nosonar: ansible:S5332` inline on each line with a note
explaining the Docker-internal context.

---

### FP2 — Portainer, Grafana, NetBox admin APIs (ACCEPTED RISK)

**Rule:** `ansible:S5332`, `python:S5332`
**Issue:** [#360](https://github.com/stevedwray/proxmox-homelab/issues/360)

| Service | Port | API type | Why HTTP is unavoidable |
|---|---|---|---|
| Portainer | 9000 | Admin bootstrap, user management | Portainer CE has no native HTTPS management port |
| Grafana | 3000 | Admin user and password setup | Would require LXC-level TLS config + cert rotation |
| NetBox | 8080 | Inventory API (token auth) | NetBox HTTP-only in this deployment |

All calls are from the Ansible control node to private SDN IPs. No external
exposure. Credentials sent are one-time bootstrap values (admin password,
API tokens), not session credentials.

**Action:** Add `# nosonar: ansible:S5332` with documented accepted-risk
rationale. Record the decision in this file for audit trail.

---

### FP3 — Teardown harness and test script health checks

**Rule:** `shell:S5332`
**Files:** `scripts/teardown-deploy-test.sh` (11 hits, lines 1436–2063),
  `scripts/test-docker-mount-resize.sh` (5 hits)

Unauthenticated liveness probes: `curl http://${ip}:9000/-/health/live/`,
`curl http://${ip}:3000/login`. No credentials, no sensitive data in
response. These are checking whether a TCP port accepts connections.

**Action:** Add `# NOSONAR` inline on each curl line.

---

### FP4 — Fixture YAML files

**Rule:** `kubernetes:S5332` (12 hits)
**Files:** `docs/provisioning-refactor/fixtures/` — all 12 hits

These are test fixtures used to validate the edge manifest parser. They
contain example URLs (including HTTP examples used to test validation
rejection). They are never deployed.

**Action:** Add `docs/provisioning-refactor/fixtures/` to
`sonar.exclusions` in `sonar-project.properties`.

---

### FP5 — Prometheus metrics server HTTP listener

**Rule:** `python:S5332`
**File:** `terraform/lxc/ansible/files/harbor_findings_exporter.py:498`

`listen_address = _env("HARBOR_FINDINGS_LISTEN_ADDRESS", "0.0.0.0")`
This is the Prometheus exporter's HTTP listener. Prometheus metrics
endpoints serving unauthenticated HTTP is the standard pattern for
VictoriaMetrics to scrape. Not a security concern.

**Action:** Add `# nosonar: python:S5332` on the line.

---

### FP6 — NetBox client HTTP URL construction

**Rule:** `python:S5332`
**File:** `terraform/lxc/stacks/netbox-stack/integrations/client.py:19`

`f"http://{os.environ.get('LAB_IP_NETBOX')}:8080"` — NetBox listens on
HTTP:8080 in this deployment. Same as FP2 (Portainer/Grafana). Private SDN.

**Action:** Add `# nosonar: python:S5332` with accepted-risk note.

---

### FP7 — curl redirect follow in dev setup script

**Rule:** `shell:S6506`
**File:** `scripts/setup-dev-env.sh:61`
**Issue:** [#363](https://github.com/stevedwray/proxmox-homelab/issues/363)

`curl -s https://api.github.com/...` — already HTTPS. S6506 fires because
curl follows redirects by default. Redirect-following is required when
downloading release assets from GitHub (GitHub uses redirects for CDN
delivery).

**Action:** Add `# nosonar: shell:S6506` inline.

---

## Code quality findings

### CQ1 — Python lint (ruff)

**Issue:** [#356](https://github.com/stevedwray/proxmox-homelab/issues/356)

24 findings across the project. Breakdown:

| Rule | Count | Fixable auto? |
|---|---|---|
| F401 (unused import) | 14 | Yes (`ruff --fix`) |
| E402 (import not at top) | 5 | No — intentional `sys.path` manipulation; add `# noqa: E402` |
| E731 (lambda assignment) | 3 | No — rewrite as `def` in `configuration.py` |
| F841 (unused variable) | 1 | Yes |

**Priority:** Must fix before PR #358 merges (new `python-lint` CI job will
block on these).

---

### CQ2 — Cognitive complexity (Python)

38 CRITICAL findings. Classified by operational priority:

**Group A — actively maintained, fix before Phase 06:**

| File | Worst function | Complexity | Issue |
|---|---|---|---|
| `netbox-stack/integrations/populate.py` | line 1256 | **118** | [#364](https://github.com/stevedwray/proxmox-homelab/issues/364) |
| `netbox-stack/integrations/discover.py` | line 321 | **100** | [#364](https://github.com/stevedwray/proxmox-homelab/issues/364) |
| `netbox-stack/integrations/client.py` | line 124 | **44** | [#364](https://github.com/stevedwray/proxmox-homelab/issues/364) |

**Group B — fix when touching for other reasons:**

| File | Worst function | Complexity | Issue |
|---|---|---|---|
| `reconcile-authentik-edge.py` | line 929 | **160** | [#365](https://github.com/stevedwray/proxmox-homelab/issues/365) |
| `ansible/files/harbor_findings_exporter.py` | line 272 | **118** | [#365](https://github.com/stevedwray/proxmox-homelab/issues/365) |
| `harbor_postconfigure/files/harbor_scan_smoke.py` | line 336 | **56** | [#365](https://github.com/stevedwray/proxmox-homelab/issues/365) |

**Group C — lower change frequency, defer:**

`classify-storage-plan.py` (101), `validate-stack-metadata.py` (79),
`validate-current-step.py` (67), `validate-plan-state.py` (56), and other
`scripts/validate-*.py` files. Tracked under [#365](https://github.com/stevedwray/proxmox-homelab/issues/365).

---

## Ansible lint

Currently passing in CI (both `terraform/lxc/ansible/` and `ansible/`
bootstrap playbooks). No new findings from the 2026-06-14 scan.
The `yaml[line-length]` warnings noted in sprint-plan Session 1d have not
surfaced as CI failures on the current branch; monitor on the next push.
