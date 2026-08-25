# nginx-test-stack (planning workspace)

Status: **plan written, not yet built.** This is a deliberate test case
for the `plan-change` -> `implement-step` process itself
(`docs/agent-design/README.md`), using a throwaway nginx container as the
example workload rather than anything that needs to exist for its own
sake.

Written with `.github/prompts/plan-change.prompt.md` per
`docs/agent-design/step-packet-schema.md`. See `plan.md` for the full
step-by-step plan.

**Two passes, by design, not a single plan:**

1. **This pass (current plan.md):** deploy + provision only. A single
   `nginx-test-stack` LXC, plain LAN bridge, stock `nginx` image, no
   integration with anything else. All 4 steps carry literal content or
   exact commands -- none are `frontier`.
2. **A second pass, later, in a fresh plan-change run:** once pass 1 is
   validated, the operator destroys this container and a new plan adds
   Traefik, technitium DNS (test zone), and monitoring integration on a
   rebuilt `nginx-test-stack`. That plan does not exist yet -- do not
   assume any of its shape from this README.

## Quick facts (pass 1 only)

| | |
|---|---|
| Stack name | `nginx-test-stack` |
| Zone | plain LAN bridge (vmbr0), no SDN zone -- matches other disposable test-tier stacks (`docker-socket-proxy-test`, `test-storage`) |
| IP / VMID | `192.168.1.54/24`, VMID `161` (both confirmed free against every `terraform/lxc/stacks/*/stack.yaml` at plan time) |
| Gateway / DNS | `192.168.1.1` / `192.168.1.1` (matches sibling test-tier stacks) |
| Image | `harbor.lab.gibbsgreatly.xyz/dockerhub/library/nginx:1.27-alpine`, pulled through Harbor's Docker Hub proxy-cache (never bare `docker.io/nginx`) |
| Persistent state | none -- stock image content only for this pass |
| `deployment_tier` / tags | `test` / `docker`, `disposable`, `test` |
| Playbook | `deploy-nginx-test-stack` (`lxc_base` + `docker_base` roles) |

## Why nginx, why this shape

nginx was chosen only because it is a minimal, well-known image with an
obvious pass/fail check (its default welcome page) -- there is nothing
nginx-specific about validating the plan-change pipeline. The scaffolding
approach (one step authoring `stack-request.yaml`, one step running
`terraform/lxc/scaffold-stack.sh`) follows
`step-packet-schema.md`'s "Reuse scaffold-stack.sh for new stacks
specifically" section, the same pattern already proven end-to-end by the
`minecraft-stack` exemplar in
`docs/stack-lifecycle-refactor/stage-10-minecraft-exemplar.md`.
