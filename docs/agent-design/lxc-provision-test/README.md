# LXC Provision Test Workspace (throwaway)

Tests the real target task class for this methodology: deploying a new
LXC container and configuring a service on it via Ansible, end to end,
one small step at a time. Everything before `lxcprov-04-provision` is
pure text authoring with zero infrastructure risk. `lxcprov-04-provision`
is the first step in this whole test arc that actually creates real
infrastructure (a new LXC on pve-test-vm) -- it waits for an explicit
go-ahead beyond the normal hand-back flow, not just "the previous step's
gate passed."

The stack itself, `smoketest-stack`, is a single disposable nginx
container -- no persistent data, nothing depends on it, safe to destroy
at any point. Delete this whole workspace once the test is done, and
tear down the real stack per `lxcprov-06-teardown` regardless of how far
the test gets.

## Step status

- `lxcprov-00-preflight-check`: not started
- `lxcprov-01-stack-request`: not started
- `lxcprov-02-scaffold` (operator step, not run via `implement-step`): not started
- `lxcprov-03-verify-generated-files`: not started
- `lxcprov-04-provision`: not started -- **do not run without explicit operator go-ahead**
- `lxcprov-05-verify-service`: not started
- `lxcprov-06-teardown` (operator step, not run via `implement-step`): not started
