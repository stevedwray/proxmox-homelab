# Hand-back Test Plan (throwaway)

One step. Testing whether implement-step writes its hand-back into this
workspace's README.md, not just a chat reply. Delete this workspace once
the test is done.

```yaml
id: handbacktest-01-write-marker
title: Write the hand-back test marker file
depends_on: []

change: >
  Create the file docs/agent-design/artifacts/handback-marker.txt
  containing exactly this text and nothing else: hand-back test marker

scope:
  allowed_paths:
    - docs/agent-design/artifacts/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: content-check
    cmd: "cat docs/agent-design/artifacts/handback-marker.txt"
    expect: "hand-back test marker"
    critical: true
```
