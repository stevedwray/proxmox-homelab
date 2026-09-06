# Phase 03 — Code Quality and Bug Fixes

## Goal

Resolve the open GitHub issues covering bugs, maintainability, and refactoring across the NetBox integration scripts and shell scripts. These are independent of infrastructure phases and can be worked on in parallel.

## Repository context

All affected files are in:
- `terraform/lxc/stacks/netbox-stack/integrations/` — Python scripts
- `scripts/` — shell scripts at the repo root
- `sync-secrets.sh` — root-level shell script

## Prerequisites

- Phase 00 (housekeeping) complete so the branch is clean
- Python 3.12 available locally for running/testing changes
- `ansible-lint` passing at 0 violations before and after changes

## Issues in this phase (ordered by priority)

| Issue | Title | Priority |
|---|---|---|
| #35 | SSL/TLS in `proxmox_client.py` | Critical — acknowledge |
| #48 | MikroTik `primary_ip4` set to WAN IP | Medium — bug fix |
| #49 | gluetun-6881 registered twice | Low — bug fix |
| #28 | Cognitive complexity in NetBox integration | Critical — refactor |
| #23 | Add explicit `return` to shell functions | Major — quick fix |
| #26 | Assign positional params to locals in shell functions | Major — quick fix |
| #31 | Extract repeated SSH options string | Minor — quick fix |
| #25 | Nested ternary in `mikrotik_client.py` | Major — refactor |
| #27 | Wrong arg types in `configuration.py` | Critical — investigate |
| #75 | Rename `harbor_installer` role vars | Low — defer |

---

## Batch 1 — Shell script maintainability (issues #23, #26, #31)

These are fast, low-risk fixes to `scripts/check-proxmox-status.sh`, `scripts/setup-dev-env.sh`, and `sync-secrets.sh`. Do them in a single branch and commit.

### Branch

```bash
git checkout -b fix/shell-maintainability baseline/teardown-validated
```

### Issue #23 — Add explicit `return 0` to shell functions

File: `scripts/check-proxmox-status.sh` — lines 20, 21, 22, 23, 63, 72, 107, 131, 147, 185, 243, 289, 293
File: `scripts/setup-dev-env.sh` — lines 12, 13, 14, 15, 18, 55, 155, 192, 226, 258, 299
File: `sync-secrets.sh` — line 54

At the end of each function body (before the closing `}`), add `return 0` if there is no existing return statement. Do not add `return 0` after a command that should propagate a non-zero exit code.

SonarCloud rule: `shelldre:S7682`

### Issue #26 — Assign positional parameters to named locals

File: `scripts/check-proxmox-status.sh` — lines 20–23 (logging functions)
File: `scripts/setup-dev-env.sh` — lines 12–15 (logging functions)
File: `sync-secrets.sh` — line 55 (`shell_single_quote`)

At the top of each affected function, add:
```bash
local message="$1"
# (use the appropriate name for each parameter)
```

Then replace all uses of `$1`, `$2`, etc., in the function body with the named variable.

SonarCloud rule: `shelldre:S7679`

### Issue #31 — Extract repeated SSH options string

File: `scripts/check-proxmox-status.sh` — lines 150 and 246

At the top of the script (after the shebang and initial variable declarations), add:

```bash
SSH_OPTS="-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no"
SEPARATOR="=============================================="
```

Replace all occurrences of the literal strings in the file with the variables. Use `$SSH_OPTS` (unquoted is fine for option strings, but double-check for word splitting issues) and `$SEPARATOR`.

SonarCloud rule: `shelldre:S1192`

### Validate and commit

```bash
# Run shellcheck if available:
shellcheck scripts/check-proxmox-status.sh scripts/setup-dev-env.sh sync-secrets.sh

git add scripts/check-proxmox-status.sh scripts/setup-dev-env.sh sync-secrets.sh
git commit -m "refactor(scripts): shell maintainability fixes

- Add explicit return 0 to shell functions (shelldre:S7682) (Closes #23)
- Assign positional params to local variables (shelldre:S7679) (Closes #26)
- Extract repeated SSH opts and separator to variables (shelldre:S1192) (Closes #31)"

git push origin fix/shell-maintainability
# Merge to baseline/teardown-validated via PR
git checkout baseline/teardown-validated && git merge fix/shell-maintainability
git push origin baseline/teardown-validated

gh issue close 23 --comment "Fixed in fix/shell-maintainability — explicit return 0 added to all shell functions."
gh issue close 26 --comment "Fixed in fix/shell-maintainability — positional params assigned to local variables."
gh issue close 31 --comment "Fixed in fix/shell-maintainability — SSH_OPTS and SEPARATOR extracted to variables."
```

---

## Batch 2 — SSL/TLS acknowledgement in proxmox_client.py (issue #35)

File: `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py`, lines 44–46

The three SonarCloud findings (`python:S5527`, `python:S4423`, `python:S4830`) are **intentional** — Proxmox uses a self-signed certificate in a homelab environment. The correct resolution is to add an inline suppression comment and acknowledge this in SonarCloud.

### Fix

Read the file around lines 44–46 first, then add a comment block immediately above the SSL-disabling code explaining the intent:

```python
# Certificate verification is intentionally disabled for the internal Proxmox API.
# The Proxmox node uses a self-signed certificate in this homelab environment.
# This is acceptable for internal LAN-only traffic. See docs/reference/proxmox-server-baseline.md.
# noqa: S5527, S4423, S4830
```

Also add a SonarCloud inline suppression if the project uses `# NOSONAR` style (check other files for the convention used). If SonarCloud accept-as-wontfix is preferred, do that via the SonarCloud UI rather than code comments.

### Commit

```bash
git add terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py
git commit -m "fix(netbox): acknowledge intentional SSL disable in proxmox_client.py (Closes #35)

Self-signed cert in homelab — certificate verification disabled intentionally.
Suppression comments added; acknowledged in SonarCloud."
git push origin baseline/teardown-validated
gh issue close 35 --comment "Acknowledged as intentional — homelab self-signed cert. Suppression comment added."
```

---

## Batch 3 — MikroTik primary_ip4 bug (issue #48)

File: `terraform/lxc/stacks/netbox-stack/integrations/populate.py`

### Root cause

`populate_network()` iterates all MikroTik interfaces and calls `nb.patch(..., primary_ip4=...)` for each one with an IP. The last interface processed wins — which is the WAN-facing interface (`121.99.xx.xx`).

### Fix

Read the `populate_network()` function first. Then modify the logic to only set `primary_ip4` when the interface's IP address is within a known internal prefix. Use a simple heuristic:

```python
INTERNAL_PREFIXES = ("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                     "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                     "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")

def _is_internal_ip(ip_str: str) -> bool:
    """Return True if the IP address is in a known internal (RFC 1918) range."""
    return ip_str.startswith(INTERNAL_PREFIXES)
```

Then gate the `primary_ip4` assignment:

```python
if _is_internal_ip(ip_address) and primary_ip4 is None:
    primary_ip4 = ip_id
```

Set `primary_ip4` only once (the first internal IP found), not on every loop iteration.

### Test

Run `populate.py` against the live NetBox (or a test run with `--dry-run` if that flag exists). Verify MikroTik device has `primary_ip4 = 192.168.1.1`.

### Commit

```bash
git add terraform/lxc/stacks/netbox-stack/integrations/populate.py
git commit -m "fix(netbox): set MikroTik primary_ip4 to LAN IP not WAN IP (Closes #48)

Only set primary_ip4 for the first RFC 1918 address found.
Previously the last interface processed (WAN) won the assignment."
git push origin baseline/teardown-validated
gh issue close 48 --comment "Fixed — primary_ip4 now set to first RFC 1918 IP found (192.168.1.1)."
```

---

## Batch 4 — gluetun service deduplication (issue #49)

File: `terraform/lxc/stacks/netbox-stack/integrations/discover.py` and/or `populate.py`

### Root cause

`gluetun-6881` appears twice in the services list — likely because gluetun port 6881 is listed for both TCP and UDP, generating two entries with the same name, or because `torrent-stack` appears in both Proxmox and Portainer discovery and services are merged without deduplication.

### Fix

1. Read `discover.py` — find the function that builds the services list (around line 101)
2. Before returning from `build_full_topology()` (or in `populate_ipam()`), deduplicate services on the tuple `(vm_id, name, port, protocol)`:

```python
def _dedup_services(services: list[dict]) -> list[dict]:
    """Remove duplicate service entries by (vm_id, name, port, protocol)."""
    seen = set()
    result = []
    for svc in services:
        key = (svc.get("vm_id"), svc.get("name"), svc.get("port"), svc.get("protocol"))
        if key not in seen:
            seen.add(key)
            result.append(svc)
    return result
```

Call `_dedup_services()` before passing services to `populate_ipam()`.

This fix will likely also emerge naturally if issue #28 (cognitive complexity refactor) breaks `build_full_topology()` into smaller functions — consider doing #28 first.

### Commit

```bash
git add terraform/lxc/stacks/netbox-stack/integrations/discover.py
git commit -m "fix(netbox): deduplicate services before NetBox population (Closes #49)

gluetun-6881 was being registered twice due to merged Proxmox+Portainer
discovery results. Added dedup on (vm_id, name, port, protocol)."
git push origin baseline/teardown-validated
gh issue close 49 --comment "Fixed — services deduplicated on (vm_id, name, port, protocol) before population."
```

---

## Batch 5 — Cognitive complexity refactor (issue #28)

File: `terraform/lxc/stacks/netbox-stack/integrations/discover.py` (function at line ~101, complexity 70)
File: `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py` (function at line ~123, complexity 53)
File: `terraform/lxc/stacks/netbox-stack/integrations/populate.py` (function at line ~133, complexity 20)

This is the largest refactor in this phase. Tackle in this order:

### discover.py (complexity 70) — highest priority

Read the entire `build_full_topology()` function. Extract it into at least these sub-functions:
- `_discover_proxmox_vms()` — query Proxmox for VMs/LXCs
- `_enrich_from_portainer()` — merge Portainer service data
- `_enrich_from_stack_yaml()` — merge stack.yaml metadata
- `_dedup_services()` — see Batch 4 above
- `_build_topology()` — orchestrate the above and return the merged result

Each sub-function should be ≤ 20 cognitive complexity. Run Sonar or a complexity checker locally to verify.

### proxmox_client.py (complexity 53)

Read the function at line ~123. Extract nested conditionals into helper methods:
- Each branch of a major `if/elif` block becomes a private method
- Common patterns (e.g., building a network interface dict) become helper functions

### populate.py (complexity 20)

This is just over the limit. Read the function and extract the most complex sub-section into a helper.

### Test after refactor

```bash
cd terraform/lxc/stacks/netbox-stack/integrations

# Dry-run or test against live NetBox:
python populate.py --dry-run 2>/dev/null || python populate.py
# Re-run to verify idempotency: 0 objects created on second run
python populate.py
```

### Commit

```bash
git add terraform/lxc/stacks/netbox-stack/integrations/
git commit -m "refactor(netbox): reduce cognitive complexity in integration scripts (Closes #28)

discover.py: build_full_topology split into 4 focused sub-functions (70 → <15)
proxmox_client.py: extract nested conditionals to helpers (53 → <15)
populate.py: extract complex sub-section (20 → <15)

Idempotency verified: clean wipe → populate → re-run yields 0 new objects."
git push origin baseline/teardown-validated
gh issue close 28 --comment "Refactored. discover.py complexity 70→<15, proxmox_client.py 53→<15, populate.py 20→<15."
```

---

---

## Batch 6 — Fix stale Harbor IP in CI (task 03-06)

One-line fix in `validate.yml`: update the `harbor-image-policy` error message from
`192.168.1.10` (old vmbr0 address) to `192.168.40.10` (current infra_seg address).

See [docs/plan/tasks/03-code-quality-06-fix-harbor-ip-in-ci.md](tasks/03-code-quality-06-fix-harbor-ip-in-ci.md).

---

## Batch 7 — Add ShellCheck to CI (task 03-07)

Add a `shellcheck` job to `validate.yml` that lints all `.sh` files on every push/PR.
Excludes `_legacy/` and `.terragrunt-cache/`. Uses `ubuntu-latest` with `apt-get install shellcheck`.

See [docs/plan/tasks/03-code-quality-07-shellcheck-ci.md](tasks/03-code-quality-07-shellcheck-ci.md).

---

## Batch 8 — Integrate SonarCloud into CI (task 03-08)

Add a `sonarcloud` job to `security-scan.yml` using `SonarSource/sonarcloud-github-action`.
Remove hardcoded `sonar.branch.name=main` from `sonar-project.properties`. Requires
`SONAR_TOKEN` repository secret to be set before the job will pass.

See [docs/plan/tasks/03-code-quality-08-sonarcloud-ci.md](tasks/03-code-quality-08-sonarcloud-ci.md).

---

## Deferred issues (do not action in this phase)

- **#25** (`mikrotik_client.py` nested ternary) — cosmetic only, no functional impact. Fix opportunistically if touching that file.
- **#27** (`configuration.py` wrong arg types) — this file is part of NetBox's own shipped configuration. Read the file header to confirm source ownership before modifying. If it is a generated/vendored file, fix should be upstream rather than in this repo.
- **#75** (harbor_installer role var renaming) — low priority, ansible-lint is in warn mode; no functional impact.

---

## Acceptance criteria

- [ ] Harbor IP `192.168.1.10` removed from CI config (task 03-06)
- [ ] `shellcheck` job present in `validate.yml` and passing (task 03-07)
- [ ] SonarCloud job present in `security-scan.yml` and passing (task 03-08)
- [ ] `shellcheck` passes on all three modified shell scripts (or no new failures)
- [ ] `scripts/check-proxmox-status.sh`, `scripts/setup-dev-env.sh`, `sync-secrets.sh` have explicit returns, named locals, and extracted string constants
- [ ] `proxmox_client.py` has a suppression comment explaining intentional SSL disable
- [ ] Issue #35 closed or acknowledged in SonarCloud
- [ ] MikroTik device in NetBox has `primary_ip4 = 192.168.1.1` after running `populate.py`
- [ ] `populate.py` produces no duplicate service registration attempts on a clean run
- [ ] NetBox integration idempotency preserved: second `populate.py` run creates 0 new objects
- [ ] Cognitive complexity of all three NetBox functions reduced to ≤20
- [ ] `ansible-lint` still passes at 0 violations (run from `terraform/lxc/ansible/`)
- [ ] Issues #23, #26, #28, #31, #35, #48, #49 all closed with commit references
