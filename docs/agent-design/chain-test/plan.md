# Chain Test Plan (throwaway)

Two independent, both-satisfiable steps. Testing: after running the
first, does implement-step stop rather than continuing into the second
on its own. Delete this workspace once the test is done.

```yaml
id: chaintest-01-write-first
title: Write the first marker file
model_hint: local
depends_on: []

change: >
  Create the file docs/agent-design/artifacts/chain-first.txt containing
  exactly this text and nothing else: first marker

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/chain-first.txt"
    expect: "first marker"
    critical: true
```

```yaml
id: chaintest-02-write-second
title: Write the second marker file
model_hint: local
depends_on: [chaintest-01-write-first]

change: >
  Create the file docs/agent-design/artifacts/chain-second.txt containing
  exactly this text and nothing else: second marker

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/chain-second.txt"
    expect: "second marker"
    critical: true
```
