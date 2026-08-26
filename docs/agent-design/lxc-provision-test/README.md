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

- `lxcprov-00-preflight-check`: not started
- `lxcprov-01-stack-request`: not started
- `lxcprov-02-scaffold` (operator step, not run via `implement-step`): not started
- `lxcprov-03-verify-generated-files`: not started
- `lxcprov-04-create-environment-config`: not started
- `lxcprov-05-terragrunt-apply`: not started -- **do not run without explicit operator go-ahead**
- `lxcprov-06-provision`: not started
- `lxcprov-07-verify-service`: not started
- `lxcprov-08-teardown` (operator step, not run via `implement-step`): not started
