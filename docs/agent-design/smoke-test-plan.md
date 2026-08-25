# Smoke Test Plan (throwaway)

Not a real workspace. Exists only to run one step through `implement-step`
end to end and observe it. Delete this file once the test is done.

```yaml
id: smoke-01-write-marker
title: Write a smoke-test marker file
model_hint: local
depends_on: []

change: >
  Create the file docs/agent-design/artifacts/smoke-marker.txt containing
  exactly this text and nothing else: step packet smoke test passed

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply run"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/smoke-marker.txt"
    expect: "step packet smoke test passed"
    critical: true
```
