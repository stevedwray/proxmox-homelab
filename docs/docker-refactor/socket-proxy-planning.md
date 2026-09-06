# Docker Socket Proxy Refactor Plan

## Goal

Make Docker runtime discovery safe and repeatable by deploying a managed,
read-only Docker socket proxy on Docker-enabled LXCs.

The first implementation target is a disposable test container and teardown-test
workflow. Existing infrastructure stacks must not be changed until the test path
is proven.

The refactor is not complete until normal rebuild/deploy of the managed
infrastructure Docker container set installs and verifies docker-socket-proxy,
and that behavior is proven by a teardown/rebuild validation on `pve`.

For the current implementation checkpoint, rollout status, and known remaining
design caveat, see `docs/docker-refactor/current-state.md`.

## Decisions To Preserve

- Manage the proxy with Ansible, not the LXC template.
- Keep it scoped to the managed infrastructure Docker container set. Do not
  expand to every Docker-capable LXC in the lab.
- Run it after `docker_base` has installed and started Docker.
- Prove the role on a disposable/test Docker LXC before enabling any real stack.
- Integrate the proof into teardown-test before stack rollout.
- Do not use Portainer or SSH as a workaround for runtime discovery.
- The disposable test target `docker-socket-proxy-test` has been proven on
  `pve-test` via Sessions 5 and 6. Until the rollout gates are satisfied, keep
  proxy enablement disabled on real stacks and use the teardown-test opt-in
  workflow to exercise the proof path.

## Working Rules For Copilot Sessions

- Use GitHub Copilot with the `GPT-5 mini` model.
- Keep each session small enough to finish, test, and write a clear handback
  document.
- Start every session by reading:
  - `AGENTS.md`
  - this plan
  - the latest local handback under `docs/docker-refactor/artifacts/`, if one
    exists
- Do not develop directly on `baseline/teardown-validated` or `baseline/teardown-validated`.
- Before disposable proof validation, confirm the target is `pve-test`.
- Before the final infrastructure-container teardown/rebuild gate, confirm the
  target is `pve`. That gate must not touch containers outside the managed
  infrastructure set.
- Use `./with-secrets <command>` for credentialed commands.
- Do not create tracked temporary reports, handoffs, or evidence.
- Put all temporary session material under the ignored local artifact path:
  - `docs/docker-refactor/artifacts/`
- Avoid bookkeeping churn. A session must produce material source changes,
  validation evidence, or a precise blocker. Handback wording changes alone do
  not count as progress.
- Keep chat minimal. Copilot should not narrate every read/search/todo update;
  it should do the work and finish with the required handback.
- Never stop without writing a handback document. If the session is complete,
  partial, blocked, or out of time, write the handback under
  `docs/docker-refactor/artifacts/` before the final response. A session
  without a handback document is incomplete and must be rejected by manager
  review.

## Handback Format

Each Copilot session must write a handback document before it stops work. This
is required even when no files changed, validation could not run, or the session
is blocked.

Write the handback under `docs/docker-refactor/artifacts/`, using a filename such
as:

```text
docs/docker-refactor/artifacts/01-role-audit-handback.md
```

The final chat response should only point to the handback file and briefly state
the status. Do not use chat-only handbacks.

Use this format:

```text
# Docker Refactor Handback: <session name>

## Status
Complete | Blocked | Partial

## Achieved
- ...

## Changed Files
- ...

## Verification
- Command: ...
  Result: pass/fail/not run

## Blockers
- None, or exact blocker with evidence

## Next Recommended Step
- ...
```

## Required Prompt Footer

Add this footer to every Copilot handoff:

```text
Keep chat minimal. Do not narrate every read/search/todo update. Do the work.

Do not stop after planning, reading files, updating todos, or asking whether to
proceed. Complete the requested session as far as possible.

Before stopping for any reason, write a handback document under:
docs/docker-refactor/artifacts/

The handback document must include the required Docker Refactor Handback
sections: Status, Achieved, Changed Files, Verification, Blockers, and Next
Recommended Step. If you are blocked, need a user decision, or make no file
changes, still write the handback document and state exactly why.

Do not stop just to ask questions. If a user decision is required, record the
question, options, and recommended default in the handback document.

Your final chat response should only say that work stopped and give the handback
document path plus status.
```

## Anti-Churn Rules

Use these rules to keep Copilot sessions focused on work that moves the refactor
forward:

- Do not run a session whose only likely output is reorganized wording.
- Do not update handbacks, reports, or this plan unless the session also
  produced source changes, validation evidence, or a precise blocker.
- Do not write "continue in the next session" unless the current session
  completed an exit criterion or found a blocker with evidence.
- If a session cannot make material progress within its scope, stop early and
  write a handback document with the exact missing input or failing command.
- Manager review should reject handbacks that only restate previous context.
- Manager review should reject any Copilot session that stops work without a
  handback document under `docs/docker-refactor/artifacts/`.

## Step-By-Step Sessions

### Session 1: Audit Existing Test Patterns

Purpose: inspect existing test-stack patterns before adding the dedicated target.

Steps:

1. Inspect the existing Docker path:
   - `terraform/lxc/ansible/roles/docker_base/`
   - Docker stack playbooks under `terraform/lxc/ansible/playbooks/`
   - `terraform/lxc/stacks/test-lxc/stack.yaml` as a source pattern only
   - `terraform/lxc/stacks/test-docker/stack.yaml` as a source pattern only
   - teardown-test docs that currently exclude `test-*` stacks
2. Use a new dedicated disposable stack named `docker-socket-proxy-test`.
3. Confirm these defaults for the test target:
   - role name: `docker_socket_proxy`
   - enable flag: `enable_docker_socket_proxy`
   - default port: `2375`
   - bind address: test LXC service IP unless the repo shows a better variable
   - proxy path: `/opt/docker-socket-proxy`
4. Decide whether the role should use Docker Compose or Ansible Docker modules.
   Prefer the repo's existing Docker deployment style.
5. Write a handback document with the `docker-socket-proxy-test` defaults and exact files to edit
   next.

Exit criteria:

- No runtime changes.
- No existing infrastructure stack is selected for rollout.
- The `docker-socket-proxy-test` target and defaults are recorded in the
  handback.

### Session 2: Add Or Prepare The Test Container

Purpose: make a disposable Docker LXC ready for proxy development.

Steps:

1. Add only the new `docker-socket-proxy-test` stack.
2. Keep the test stack clearly excluded from normal platform rebuild scope
   unless teardown-test explicitly opts it in.
3. Ensure the test LXC has Docker and at least one harmless container workload
   for discovery, such as nginx, whoami, or redis.
4. Add only the minimal playbook or metadata needed to deploy this test target.
5. Run source checks that do not require live infrastructure.
6. Write a handback document with changed files and the exact command that will deploy the test LXC.

Exit criteria:

- The `docker-socket-proxy-test` target exists in source.
- Existing infra stacks are untouched.
- The handback explains how teardown-test can opt into the target later.

### Session 3: Add The Ansible Role

Purpose: create the opt-in proxy role without changing any real stack rollout.

Steps:

1. Add `terraform/lxc/ansible/roles/docker_socket_proxy/`.
2. Add role defaults for:
   - `enable_docker_socket_proxy: false`
   - image name and version
   - listen address and port
   - allowed read-only API sections
   - project directory
3. Add tasks that do nothing when the enable flag is false.
4. When enabled, deploy an idempotent proxy service.
5. Ensure the service exposes read-only Docker endpoints only.
6. Add a validation task for `/containers/json?all=1`.
7. Add rollback/removal behavior for disabled hosts if that fits the chosen
   deployment style.
8. Run `ansible-playbook --syntax-check` on a playbook that can load the role.
9. Write a handback document with changed files, defaults, and syntax-check result.

Exit criteria:

- Role exists.
- Disabled-by-default behavior is explicit.
- Syntax check passes, or the blocker is exact.

### Session 4: Wire The Role Only Into The Test Path

Purpose: make the role deployable on the disposable test LXC only.

Steps:

1. Add the role after `docker_base` only in the
   `docker-socket-proxy-test` playbook/path.
2. Set `enable_docker_socket_proxy: true` only for the test target.
3. Keep every existing infra stack disabled and unchanged.
4. Run syntax checks for changed playbooks.
5. Write a handback document with the exact test deployment and rollback commands.

Exit criteria:

- The proxy role can run on the test target.
- No existing infra stack has proxy enablement.

### Session 5: Prove On The Disposable Test LXC

Purpose: validate behavior on pve-test without touching real stacks.

Steps:

1. Verify the target first:

   ```text
   ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
   ```

   It must print `pve-test`.
2. Deploy the `docker-socket-proxy-test` disposable LXC.
3. Verify Docker is running on the test LXC.
4. Verify the proxy endpoint with:

   ```text
   /containers/json?all=1
   ```

5. Attempt at least one mutating endpoint or method and confirm it is blocked.
6. Destroy or reset the test target if the session scope requires clean teardown.
7. Write a handback document with endpoint evidence, blocked mutation evidence, and cleanup status.

Exit criteria:

- The disposable test LXC proves read-only Docker discovery works.
- Mutating Docker API access is blocked.
- Existing infra stacks remain untouched.

### Session 6: Add Teardown-Test Coverage

Purpose: make the disposable proof repeatable through the teardown-test workflow.

Steps:

1. Review the Session 5 handback.
2. Add an explicit teardown-test opt-in path for the Docker proxy test target.
3. Keep the default platform rebuild scope unchanged.
4. Add validation steps that prove:
   - the test LXC is created
   - the proxy is reachable
   - read-only container discovery works
   - mutation is blocked
   - teardown removes the test target cleanly
5. Store raw evidence only under ignored evidence paths.
6. Write a handback document with the exact teardown-test command and expected evidence files.

Exit criteria:

- The proxy proof can be run as a repeatable teardown-test exercise.
- Normal platform teardown remains unchanged unless explicitly opted in.

### Session 7: Prepare NetBox Integration, Still Disabled

Purpose: prepare future consumer wiring without enabling existing stacks.

Steps:

1. Review the teardown-test proof handback.
2. Check current NetBox discovery config and code paths for:

   ```text
   DOCKER_SOCKET_PROXY_URL_TEMPLATE=http://{guest_ip}:2375
   ```

3. Add docs or disabled config only if needed.
4. Do not enable `netbox-stack`.
5. Write a handback document with the exact changes needed for a later NetBox rollout.

Exit criteria:

- NetBox integration is understood and documented.
- No existing infra stack is changed or redeployed.

### Session 8: Close Documentation And Gates

Purpose: make the refactor maintainable and ready for manager review.

Steps:

1. Update durable docs only:
   - this plan if decisions changed
   - teardown-test docs for the disposable proof path
   - relevant test stack contract docs
   - NetBox docs only if deferred status wording changed
2. Run the required scans for changed file types:

   ```text
   ./with-secrets /home/steve/.local/bin/sonar-scanner
   ```

3. If Terraform files changed, also run:

   ```text
   /home/steve/.local/bin/snyk iac test terraform/
   ```

4. Stop if scans report new issues.
5. Write a handback document with final changed files, validation evidence, and remaining risks.

Exit criteria:

- Durable docs match the implemented state.
- Required scans pass, or new findings are handed back for decision.

## Infrastructure Rollout Gate

The disposable `pve-test` proof is necessary but not sufficient. This refactor
is complete only when socket-proxy enablement is proven through a teardown and
rebuild of the managed infrastructure Docker containers on `pve`.

Do not call the Docker refactor finished until all are true:

1. The disposable test LXC proof passes.
2. The teardown-test opt-in path passes.
3. The manager review accepts the handbacks.
4. Deploy-time socket-proxy enablement is implemented for the managed
   infrastructure Docker container set.
5. A `pve` infrastructure-container teardown/rebuild validation passes.
6. The validation proves socket-proxy endpoints are reachable on each expected
   rebuilt infrastructure Docker container.
7. The validation proves mutating Docker API access remains blocked.
8. NetBox `populate.py --plan` can see the expected runtime service changes
   after rebuild.

The `pve` gate must not touch containers outside the managed infrastructure
container set.

## Real-Stack Rollout Scope

When this work moves beyond the disposable proof path, limit rollout candidates
to the managed infrastructure Docker stacks only:

- `authentik-stack`
- `harbor-stack`
- `monitoring-stack`
- `netbox-stack`
- `portainer-stack`
- `proxy-stack`

Do not expand this workstream to every Docker-capable LXC in the lab.

### Proposed Controlled Rollout Order (Session 12 recommendation)

1. portainer-stack — low-risk, independent management server; easiest verification signal.
2. monitoring-stack — observability stack; provides logs and metrics for validation and signal.
3. netbox-stack — control-plane consumer; enables populate verification and local coverage.
4. harbor-stack — registry; moderate blast radius and dependency hub; deploy after telemetry is confirmed.
5. proxy-stack — Traefik edge; higher blast radius and external exposure; defer to near-final stages.
6. authentik-stack — identity provider; highest sensitivity and criticality; roll out last.

Rationale: start with an isolated, easily-verified host to gather signal, then expand
into observability and control-plane hosts before touching high-sensitivity or
edge-facing services.

Explicitly out of rollout scope for this plan:

- `ci-runner-01`
- `apt-cacher-stack`
- `dns-stack`
- `step-ca-stack`
- legacy or manually managed Docker LXCs outside the managed infrastructure
  stack set

## Required Remaining Implementation

The current repository state wires the `docker_socket_proxy` role into several
Docker stack playbooks, but normal deploy does not automatically enable it.
Tracked stack metadata still commonly contains:

```yaml
enable_docker_socket_proxy: false
```

and static inventories do not carry socket-proxy bind/listen variables.

The remaining implementation sessions should do practical source work:

1. Decide the exact infrastructure Docker stack set that must be rebuilt and
   validated on `pve`.
2. Add or repair metadata propagation so deploy-time Ansible receives:
   - `enable_docker_socket_proxy`
   - `docker_socket_proxy_bind_addr`
   - `docker_socket_proxy_listen_port`
3. Enable socket-proxy only for the managed infrastructure Docker stacks in
   scope.
4. Add a validation command/script that checks each expected endpoint:
   - `GET /containers/json?all=1` succeeds
   - mutating Docker API access is blocked
5. Run the final gate on `pve` only for infrastructure containers.

## Manager Review Loop

After each Copilot session:

1. Review the handback against that session's exit criteria.
2. Check `git status --short` for unexpected tracked files.
3. Confirm any handback/report artifacts are ignored.
4. Decide whether to continue, revise the next session, or stop for a fix.
5. Only commit after the fix is verified.

## Current Security Baseline

The proxy must not expose a raw Docker API.

Required constraints:

- read-only API sections only
- no container start/stop/create/delete access
- no direct `/var/run/docker.sock` mount into NetBox
- no SSH fallback as the normal runtime inspection path
- internal lab network exposure only

Docker metadata can reveal service names, images, ports, labels, and
environment-derived hints. Treat the proxy as internal infrastructure.

## Relationship To NetBox

NetBox is ready to consume Docker runtime data once this refactor exists.

Until then:

- Proxmox and MikroTik reconciliation remains accepted.
- Docker runtime service scraping remains deferred.
- Portainer should not be used as a workaround.
- SSH should not be expanded as a workaround.

## Explicitly Out Of Scope For This Plan

The purpose of this workstream is to create a repeatable, deployable method to
gather Docker runtime data through a managed, read-only `docker-socket-proxy`
so NetBox can discover services on Docker-enabled LXCs that are not enrolled in
Portainer.

The following related work is intentionally out of scope here:

- migrating environments from an old Portainer instance to the new Portainer
  instance
- building a Portainer API export/import or replay tool
- using Portainer backup/restore as the primary solution for Docker runtime
  discovery

Those may become a separate portability/migration workstream later. If that
work is taken on, treat it as a Portainer migration problem, not as part of the
socket-proxy methodology itself.
