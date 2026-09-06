# Graylog Integration Test Workspace

Status: **not started.**

Tests the next rung of the agent-design methodology beyond bare LXC
provisioning (`docs/agent-design/lxc-provision-test/`): adding a real
platform integration -- Graylog log forwarding -- to an already-deployed
stack, one bounded step at a time. See
`docs/agent-design/validation-methodology.md` for the general process
this exercise follows, and
`docs/agent-design/README.md`'s dependency-graph discussion for why
Graylog was picked as the first integration to test (self-contained in
the new stack's own files, push-based, no shared stack's config or
already-running deploy needs touching -- the lowest blast-radius of the
four integrations a real stack picks up: DNS/Traefik, Graylog, Grafana
monitoring, Authentik OIDC).

Reuses the same disposable target as the first worked example --
`smoketest-stack`, a single nginx container, VMID 99010,
`192.168.1.99/24` -- since the deploy/provision pipeline itself is
already proven and doesn't need re-validating from scratch. This plan
skips the `stack-request.yaml` / `scaffold-stack.sh` detour entirely:
that tool is still banned from local-model use (it shells out to
OpenCode internally -- see `validation-methodology.md`), so the plan
has the local model author the five real stack files directly with
literal content, which is the actual current methodology, not a
historical fallback.

**The new capability under test**: after the stack is live (steps
`gli-00` through `gli-07`, functionally identical in shape to
`lxc-provision-test`), add the `rsyslog_forward` Ansible role to the
stack's own playbook, reprovision, and verify a real log line from the
container actually lands in Graylog -- via Graylog's REST search API,
not just "the role ran without error." No other stack in this repo
currently uses `rsyslog_forward` this way (only `graylog-stack` itself
uses the role, to forward its own local logs and act as the inbound
relay) -- this is a genuinely new integration pattern for a normal
stack, not a copy of an existing one.

## Step status

- `gli-00-preflight-check`: not started
- `gli-01-stack-files`: not started
- `gli-02-playbook`: not started
- `gli-03-verify-generated-files`: not started
- `gli-04-create-environment-config`: not started
- `gli-05-terragrunt-apply`: not started -- **do not run without explicit operator go-ahead**
- `gli-06-provision`: not started
- `gli-07-verify-service`: not started
- `gli-08-add-rsyslog-forward-role`: not started
- `gli-09-reprovision`: not started -- **do not run without explicit operator go-ahead**
- `gli-10-emit-verification-log`: not started
- `gli-11-verify-in-graylog`: not started
- `gli-12-teardown` (operator step, not run via `implement-step`): not started
