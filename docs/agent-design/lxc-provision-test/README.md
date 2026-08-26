# LXC Provision Test Workspace (throwaway)

Tests the real target task class for this methodology: deploying a new
LXC container and configuring a service on it via Ansible, end to end,
one small step at a time.

**Gap found and fixed 2026-08-26** (see `plan.md`'s own note): the plan
originally jumped straight from "files authored" to running
`provision.sh`, on the wrong assumption that `provision.sh` alone takes
a brand-new stack from nothing to running. It doesn't -- it only runs
the Ansible phase and requires `inventory.yml` to already exist, which
only a real `terragrunt apply` generates. Two steps were missing
entirely (`lxcprov-04-create-environment-config`,
`lxcprov-05-terragrunt-apply`); the plan now includes them, and the
former `lxcprov-04`/`lxcprov-05` are renumbered `lxcprov-06`/`lxcprov-07`.

Everything through `lxcprov-04` is pure text authoring with zero
infrastructure risk. `lxcprov-05-terragrunt-apply` is the first step in
this whole test arc that actually creates real infrastructure (a new
LXC on pve-test-vm) -- it waits for an explicit go-ahead beyond the
normal hand-back flow, not just "the previous step's gate passed."

The stack itself, `smoketest-stack`, is a single disposable nginx
container -- no persistent data, nothing depends on it, safe to destroy
at any point. Delete this whole workspace once the test is done, and
tear down the real stack per `lxcprov-08-teardown` regardless of how far
the test gets.

## Step status

- `lxcprov-00-preflight-check`: done — ran the two preflight commands; no file changes made. Gate `vmid-free` passed (grep found no existing stack claiming vmid 99010, exit 0). Gate `ip-free` passed (ping to 192.168.1.99 got 100% packet loss / no reply, exit 0)
- `lxcprov-01-stack-request`: done — created `terraform/lxc/stacks/smoketest-stack/stack-request.yaml` with the exact content specified in the plan (stack_yaml, compose_requirements, compose_forbidden, contract_facts, playbook_content sections). Gate `stack-request-exists` passed (`test -f ...` exit 0). Gate `stack-request-parses` passed (`python3 -c "import yaml; yaml.safe_load(...)"` exit 0). **Note found later:** the embedded `playbook_content` string has broken indentation (missing space after `path:`, misaligned `dest:`/`host:`/`ignore_errors:` lines) -- harmless, since this file is scaffolding input only and isn't consumed by the real deploy pipeline, but a real transcription slip the gate (outer-YAML-only parse) didn't catch.
- `lxcprov-02-scaffold` (operator step, not run via `implement-step`): **attempted, failed partway** — `terraform/lxc/scaffold-stack.sh smoketest-stack` ran; its `stack-yaml-writer` sub-agent silently produced no `stack.yaml`, and its validator didn't catch that (it only re-checks pre-existing stacks' metadata, not "did the new stack's own file land"); the real failure only surfaced two steps later at `compose-writer`. Operator explicitly directed **no further use of OpenCode** for this test. Resolution: the frontier model authored all five files directly (Claude Code, not `implement-step`, not OpenCode) using the exact literal values already committed in `stack-request.yaml`, modeled on `terraform/lxc/stacks/harness-target/`'s real file formats.
- `lxcprov-03-verify-generated-files`: **done, run directly by the frontier model, not via `implement-step`** (nothing to compare against for drift since the files were authored straight from spec) — all four gates run for real and passed: `compose-parses` (`docker compose config`, exit 0), `correct-image-pinned` (exit 0), `no-latest-tag` (exit 0), `no-volumes` (exit 0). Also ran the real scaffold validators (`validate-compose.sh`, `validate-stack-metadata.sh`, `ansible-playbook --syntax-check`) -- all passed.
- `lxcprov-04-create-environment-config`: done — created `terraform/lxc/environments/pve-test-vm/smoketest-stack/terragrunt.hcl`, byte-identical to `terraform/lxc/environments/pve-test-vm/harness-target/terragrunt.hcl` (`diff` exit 0, confirmed independently). Gate `env-terragrunt-exists` passed. Gate `matches-existing-pattern` initially failed on a missing trailing newline; self-corrected with a targeted `printf '\n' >>` rather than rewriting the file, then passed. **Note:** `implement-step` did not write this hand-back itself this time (chat reply claimed completion, but no README edit landed) -- written here by the frontier model after independently verifying the actual result. Worth watching: the hand-back fix seems to hold for short steps but may degrade on longer ones with several tool calls/corrections.
- `lxcprov-05-terragrunt-apply`: done — ran `./with-secrets terragrunt --working-dir terraform/lxc/environments/pve-test-vm/smoketest-stack apply -auto-approve` after operator go-ahead. **Real infrastructure created**: VMID 99010 (`smoketest-stack`) is running on pve-test-vm; `terraform/lxc/environments/pve-test-vm/smoketest-stack/inventory.yml` was generated correctly (IP 192.168.1.99, correct vmid, `ansible_playbook: deploy-smoketest-stack`), confirmed independently. **Note:** hand-back skipped a third time despite the added reinforcement -- this now looks less like "doesn't know to write it" and more like deprioritizing the housekeeping edit once the real task feels complete on a longer/eventful step. Written here by the frontier model after independently verifying the actual result.
- `lxcprov-06-provision`: done — ran `./with-secrets scripts/provision.sh --stack smoketest-stack` after operator go-ahead. Both gates passed (`target-node-is-test-vm`, `provision-exits-clean` -- Ansible run `ok=61, changed=32, failed=0`). **Real service deployed and confirmed independently**: `curl http://192.168.1.99/` returns nginx's actual default welcome page. **Note:** hand-back skipped a fourth time, even with the pre-reply checkpoint fix. Three distinct wording-based fixes across this test arc (reinforced rule, "regardless of how much work" framing, pre-reply checkpoint) have now all failed on this exact case. This is a genuine, persistent limitation of this local model on long/multi-tool-call steps, not something more prompt wording is likely to fix -- see `docs/agent-design/README.md`'s note on this. Written here by the frontier model after independently verifying the actual result, per the compensating-review practice.
- `lxcprov-07-verify-service`: not started
- `lxcprov-08-teardown` (operator step, not run via `implement-step`): not started
