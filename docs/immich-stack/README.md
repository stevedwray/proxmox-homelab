# immich-stack (planning workspace)

Status: **plan written, not yet built.** This is the live first test of the
`plan-change`/`implement-step` methodology (see
`docs/agent-design/step-packet-schema.md`), not a committed decision to
deploy Immich yet. Zone (new `media_seg`, VLAN 80) and storage (NFS,
matching media-stack's existing `/nas-media/` pattern) are decided --
`plan.md` now has three real steps (`immich-00` create the zone,
`immich-01` author `stack-request.yaml`, `immich-02` run
`scaffold-stack.sh`). None have been executed yet.

See `plan.md` for the steps. See
`docs/stack-lifecycle-refactor/stage-10-minecraft-exemplar.md` for the
precedent this follows (same "author a stack-request.yaml, then run
`scaffold-stack.sh`" split, there proven with OpenCode/Ollama on
minecraft-stack).
