# Agent Prompt: Shell Maintainability + SonarCloud Suppressions

Closes: #23, #26, #31, #35, #27

---

You are working in the git repo at `/home/steve/git/proxmox-homelab`, currently on branch `dev/pve-test`.

## Task

Make all changes below, then commit and push per the instructions at the end.

---

### 1. Create branch

```bash
git checkout -b fix/shell-maintainability dev/pve-test
```

---

### 2. Issue #31 — Extract repeated SSH options to a variable (shelldre:S1192)

File: `scripts/check-proxmox-status.sh`

The string `"-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no"` is declared as `local ssh_opts=...` inside four separate functions: `test_ssh_connectivity` (line ~75), `test_proxmox_configuration` (line ~110), `test_resources` (line ~134), and `get_system_info` (line ~150).

- Remove all four `local ssh_opts=...` declarations inside those functions.
- Add a single script-level constant near the top of the file (after the `AUTOMATION_USER=` line): `SSH_OPTS="-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no"`
- Replace every use of `$ssh_opts` in the file with `$SSH_OPTS`.

---

### 3. Issue #26 — Assign positional parameters to local variables (shelldre:S7679)

The one-liner logging functions in each file use `$1` directly rather than a named local. Apply this fix:

**`scripts/check-proxmox-status.sh`** and **`scripts/setup-dev-env.sh`** — the `log_info`, `log_success`, `log_warning`, `log_error` functions look like:
```bash
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
```
Expand each to multi-line, add `local message="$1"`, and use `$message`:
```bash
log_info() {
    local message="$1"
    echo -e "${BLUE}[INFO]${NC} $message"
}
```
Apply the same pattern to `log_success`, `log_warning`, `log_error` in both files (note: in `check-proxmox-status.sh`, `log_success` and `log_error` also modify counters — keep those lines).

**`sync-secrets.sh`** — the `shell_single_quote` function uses `$1` directly. Add `local value="$1"` at the top of the function body and replace `"$1"` with `"$value"`.

---

### 4. Issue #23 — Add explicit `return 0` to shell functions (shelldre:S7682)

For every multi-line function in `scripts/check-proxmox-status.sh`, `scripts/setup-dev-env.sh`, and `sync-secrets.sh` that does not already end with an explicit `return` or `exit` statement, add `return 0` as the last statement before the closing `}`.

Do NOT add `return 0` if the function ends with a command whose exit code should propagate (e.g. the last line is a `run_check` call or a command that might legitimately fail and the function has no `set -e` safety net). In practice: add it to all informational/setup functions that currently just fall off the end.

---

### 5. Issue #35 — Add NOSONAR suppression to proxmox_client.py SSL code

File: `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py`

Find the block that disables SSL verification (around line 44):
```python
        # Disable SSL cert verification for self-signed homelab certs
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
```

Add `# NOSONAR` to each of the two SSL-disabling lines:
```python
        # Disable SSL cert verification for self-signed homelab certs
        ctx = ssl.create_default_context()
        ctx.check_hostname = False  # NOSONAR: intentional — homelab self-signed cert
        ctx.verify_mode = ssl.CERT_NONE  # NOSONAR: intentional — homelab self-signed cert
```

---

### 6. Issue #27 — Exclude vendored configuration.py from SonarCloud

File: `sonar-project.properties`

The file `terraform/lxc/stacks/netbox-stack/configuration/configuration.py` is vendored from the upstream `netbox-docker` project (its header says "We recommend to not edit this file"). Add it to the sonar exclusions line so SonarCloud stops flagging it.

Current line:
```
sonar.exclusions=**/.terraform/**,**/terraform/.terraform/**,**/_legacy/**,**/_archive/**,.env,.env.*
```

Add `,**/netbox-stack/configuration/**` to the end of that line.

---

### 7. Validate and commit

```bash
# Validate shell syntax (if shellcheck is available)
shellcheck scripts/check-proxmox-status.sh scripts/setup-dev-env.sh sync-secrets.sh 2>/dev/null || true

git add scripts/check-proxmox-status.sh scripts/setup-dev-env.sh sync-secrets.sh \
        terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py \
        sonar-project.properties

git commit -m "fix(quality): shell maintainability and SonarCloud suppressions

- Extract SSH_OPTS constant — remove 4 local redeclarations (Closes #31)
- Assign positional params to named locals in log functions (Closes #26)
- Add explicit return 0 to shell functions (Closes #23)
- Add NOSONAR to intentional SSL disable in proxmox_client.py (Closes #35)
- Exclude vendored netbox configuration.py from SonarCloud (Closes #27)"

git push origin fix/shell-maintainability

# Merge to dev/pve-test
git checkout dev/pve-test
git merge fix/shell-maintainability
git push origin dev/pve-test

# Close issues
gh issue close 23 --comment "Fixed in fix/shell-maintainability — explicit return 0 added to all shell functions."
gh issue close 26 --comment "Fixed in fix/shell-maintainability — positional params assigned to named locals."
gh issue close 31 --comment "Fixed in fix/shell-maintainability — SSH_OPTS extracted to script-level constant."
gh issue close 35 --comment "Acknowledged as intentional — homelab self-signed cert. NOSONAR comments added."
gh issue close 27 --comment "Vendored file excluded from SonarCloud via sonar.exclusions in sonar-project.properties."
```
