# Hand-back Depends Test Plan (throwaway)

Two steps, second depends on first. Run each in a **separate** chat
session -- the point is testing whether the second session can tell the
first step is done purely from the hand-back in README.md, with no
memory of running it. Delete this workspace once the test is done.

```yaml
id: hbdep-01-write-first
title: Write the first marker file
depends_on: []

change: >
  Create the file docs/agent-design/artifacts/hbdep-first.txt containing
  exactly this text and nothing else: first marker

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/hbdep-first.txt"
    expect: "first marker"
    critical: true
```

```yaml
id: hbdep-02-write-second
title: Write the second marker file
depends_on: [hbdep-01-write-first]

change: >
  Create the file docs/agent-design/artifacts/hbdep-second.txt containing
  exactly this text and nothing else: second marker

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/hbdep-second.txt"
    expect: "second marker"
    critical: true
```
