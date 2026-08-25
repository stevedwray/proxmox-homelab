# Depends Test Plan (throwaway)

Two steps, the second depending on the first. Testing: what happens when
`implement-step` is asked to run the second step directly, before the
first has landed. Delete this workspace once the test is done.

```yaml
id: depends-01-create-base
title: Create the base marker file
model_hint: local
depends_on: []

change: >
  Create the file docs/agent-design/artifacts/depends-base.txt containing
  exactly this text and nothing else: base marker

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/depends-base.txt"
    expect: "base marker"
    critical: true
```

```yaml
id: depends-02-append-line
title: Append a second line to the base marker
model_hint: local
depends_on: [depends-01-create-base]

change: >
  Add a second line to docs/agent-design/artifacts/depends-base.txt
  containing exactly this text: dependent marker

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/depends-base.txt"
    expect: "dependent marker"
    critical: true
```
