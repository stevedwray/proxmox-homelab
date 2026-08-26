# LXC Provision Test Workspace (throwaway)

Tests the real target task class for this methodology: deploying a new
LXC container and configuring a service on it via Ansible, end to end,
one small step at a time.

**Second pass, 2026-08-26.** The first pass found and fixed two real
gaps: a missing pair of steps (`lxcprov-04-create-environment-config`,
`lxcprov-05-terragrunt-apply` -- `provision.sh` alone was never
sufficient, it only runs the Ansible phase and needs `inventory.yml`
from a real `terragrunt apply` first), and an imprecise gate on
`lxcprov-06-provision` (`provision.sh` exits 0 even when it silently
skips a stack, so a bare exit-code gate couldn't catch that). Both are
fixed in `plan.md` now. Full teardown of the first pass's real
infrastructure is complete (`terragrunt destroy`, confirmed via `pct
list` -- VMID 99010 no longer exists) and all generated files removed.
This pass starts genuinely from scratch, testing whether the corrected
plan now lets `implement-step` get all the way to a running service
without needing frontier intervention along the way.

Everything through `lxcprov-04` is pure text authoring with zero
infrastructure risk. `lxcprov-05-terragrunt-apply` is the first step
that actually creates real infrastructure (a new LXC on pve-test-vm) --
it waits for an explicit go-ahead beyond the normal hand-back flow, not
just "the previous step's gate passed."

The stack itself, `smoketest-stack`, is a single disposable nginx
container -- no persistent data, nothing depends on it, safe to destroy
at any point. Delete this whole workspace once the test is done, and
tear down the real stack per `lxcprov-08-teardown` regardless of how far
the test gets.

## Step status

- `lxcprov-00-preflight-check`: **done** (2026-08-26)
  - Ran `grep -rl "vmid: 99010" terraform/lxc/stacks/*/stack.yaml` → exit code 1 (no matches, VMID free) ✅
  - Ran `ping -c 2 -W 1 192.168.1.99` → 100% packet loss, exit code 1 (IP appears free) ✅
  - No file changes made — this step only checks current state
- `lxcprov-01-stack-request`: **done** (2026-08-26)
  - Created `terraform/lxc/stacks/smoketest-stack/stack-request.yaml` with exact content from the plan: stack_yaml, compose_requirements, compose_forbidden, contract_facts, and playbook_content sections
  - Gate `stack-request-exists`: ✅ Pass (exit code 0 — file exists)
  - Gate `stack-request-parses`: ✅ Pass (exit code 0 — valid YAML)
- `lxcprov-02-scaffold` (operator step, not run via `implement-step`): **done, authored directly by the frontier model, no OpenCode used** (2026-08-26) — created all 5 files (`stack.yaml`, `docker-compose.yml`, `STACK_CONTRACT.md`, `terragrunt.hcl`, `terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml`) from the literal values in `stack-request.yaml`, matching `terraform/lxc/stacks/harness-target/`'s real formats. Real validators both passed: `validate-compose.sh` and `ansible-playbook --syntax-check`.
- `lxcprov-03-verify-generated-files`: **done** (2026-08-26)
  - Compared all five scaffolded files against stack-request.yaml literal requirements:
    - `docker-compose.yml`: image nginx:1.27-alpine ✅, port 80:80/tcp only ✅, no volumes ✅, container_name smoketest-stack-web ✅, restart unless-stopped ✅, single service ✅, no env vars ✅
    - `stack.yaml`: vmid 99010 ✅, ip 192.168.1.99/24 ✅, all fields match stack-request.yaml ✅
    - `STACK_CONTRACT.md`: matches contract_facts (vmbr0 zone, IP/gateway/VMID correct) ✅
    - `terragrunt.hcl`: present and valid ✅
    - `deploy-smoketest-stack.yml`: playbook content matches plan exactly ✅
  - Gate `compose-parses`: ✅ Pass (exit code 0 — docker compose config succeeds; only a warning about obsolete version attribute, which is non-fatal)
  - Gate `correct-image-pinned`: ✅ Pass (exit code 0 — nginx:1.27-alpine found)
  - Gate `no-latest-tag`: ✅ Pass (exit code 0 — no latest tag found)
  - Gate `no-volumes`: ✅ Pass (exit code 0 — no volumes block present)
- `lxcprov-04-create-environment-config`: not started
- `lxcprov-05-terragrunt-apply`: not started -- **do not run without explicit operator go-ahead**
- `lxcprov-06-provision`: not started
- `lxcprov-07-verify-service`: not started
- `lxcprov-08-teardown` (operator step, not run via `implement-step`): not started
