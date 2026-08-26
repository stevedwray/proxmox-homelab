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

- `lxcprov-00-preflight-check`: done — ran the two preflight commands; no file changes made. Gate `vmid-free` passed (grep found no existing stack claiming vmid 99010, exit 0). Gate `ip-free` passed (ping to 192.168.1.99 got 100% packet loss / no reply, exit 0)
- `lxcprov-01-stack-request`: done — created `terraform/lxc/stacks/smoketest-stack/stack-request.yaml` with the exact content specified in the plan (stack_yaml, compose_requirements, compose_forbidden, contract_facts, playbook_content sections). Gate `stack-request-exists` passed (`test -f ...` exit 0). Gate `stack-request-parses` passed (`python3 -c "import yaml; yaml.safe_load(...)"` exit 0)
- `lxcprov-02-scaffold` (operator step, not run via `implement-step`): **attempted, failed partway** — `terraform/lxc/scaffold-stack.sh smoketest-stack` ran; its `stack-yaml-writer` sub-agent silently produced no `stack.yaml`, and its validator didn't catch that (it only re-checks pre-existing stacks' metadata, not "did the new stack's own file land"); the real failure only surfaced two steps later at `compose-writer`. Operator explicitly directed **no further use of OpenCode** for this test. Resolution: the frontier model authored all five files directly (Claude Code, not `implement-step`, not OpenCode) using the exact literal values already committed in `stack-request.yaml`, modeled on `terraform/lxc/stacks/harness-target/`'s real file formats.
- `lxcprov-03-verify-generated-files`: **done, run directly by the frontier model, not via `implement-step`** (nothing to compare against for drift since the files were authored straight from spec) — all four gates run for real and passed: `compose-parses` (`docker compose config`, exit 0), `correct-image-pinned` (exit 0), `no-latest-tag` (exit 0), `no-volumes` (exit 0). Also ran the real scaffold validators (`validate-compose.sh`, `validate-stack-metadata.sh`, `ansible-playbook --syntax-check`) -- all passed.
- `lxcprov-04-provision`: not started -- **do not run without explicit operator go-ahead**
- `lxcprov-05-verify-service`: not started
- `lxcprov-06-teardown` (operator step, not run via `implement-step`): not started
