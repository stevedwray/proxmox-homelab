# Compose Edit Test Plan (throwaway)

Not a real workspace. Exists only to test the shape a real plan step
actually takes -- edit a compose file, run a syntax-check gate -- through
`implement-step`, end to end. Delete this file once the test is done.

```yaml
id: composetest-01-add-cache-service
title: Add a cache service to the test compose file
model_hint: local
depends_on: []

change: >
  Edit docs/agent-design/artifacts/compose-test/docker-compose.yml to add
  a new `cache` service below the existing `web` service, at the same
  indentation level. Add exactly this block, nothing else:
  cache:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]

scope:
  allowed_paths:
    - docs/agent-design/artifacts/compose-test/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply / docker compose up run"

gates:
  - id: syntax-check
    cmd: "docker compose -f docs/agent-design/artifacts/compose-test/docker-compose.yml config"
    expect: "exit 0"
    critical: true
  - id: image-check
    cmd: "grep -c 'redis:7-alpine' docs/agent-design/artifacts/compose-test/docker-compose.yml"
    expect: "1"
    critical: true
```
