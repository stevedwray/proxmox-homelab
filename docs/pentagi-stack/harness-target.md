# `harness-target` — dedicated PentAGI test-harness target

A small, purpose-built target for the automated test harness described in
[test-harness-design.md](./test-harness-design.md), standing in for
Metasploitable2 where a smaller, non-iconic, always-repeatable target is
preferable. See that doc's "target reset" discussion for why Metasploitable2
itself isn't a good fit for repeated automated runs.

## Why this target, not Metasploitable2

- **Small**: exactly two services, not dozens.
- **Not iconic**: neither service self-identifies as a lab target the way
  Metasploitable2's hostname (`metasploitable.localdomain`) does — nmap
  just reports "Apache Tomcat" / "Redis 7.4," sidestepping the
  training-data-recitation risk discussed earlier in this engagement.
- **No brute-force temptation**: Struts2's RCE needs no credentials at
  all; Redis has no auth mechanism to guess in the first place.
- **Non-trivial**: both require real, service-specific exploitation
  knowledge (a correct OGNL payload; recognizing an unauthenticated-Redis
  misconfiguration), not a banner-grab.
- **Never needs a reset between runs**: Struts2's exploit is a stateless
  per-request OGNL injection (no server-side state changes as long as
  read-only commands are used); Redis runs with zero persistence
  (`--save "" --appendonly no`, no volume) so it starts completely empty
  on every container restart — self-resetting by construction.

## Services

| Service | Image | Port | Vulnerability | Evidence |
|---|---|---|---|---|
| `harness-target-struts2` | `harbor.lab.gibbsgreatly.xyz/dockerhub/vulhub/struts2:2.3.30` | 8080/tcp | CVE-2017-5638 (S2-045) — unauthenticated OGNL injection via the `Content-Type` header | Command execution output (confirmed live: `id` → `uid=0(root) gid=0(root) groups=0(root)`) |
| `harness-target-redis` | `harbor.lab.gibbsgreatly.xyz/dockerhub/library/redis:7.4` | 6379/tcp | Unauthenticated access (`--protected-mode no`) | Seeded marker key `internal:api_key`, re-seeded on every deploy since the container has no persistence |

## Infrastructure

- Node: `pve-test-vm` (not `pve` — deliberately avoids production; see
  `test-harness-design.md` for why Metasploitable2 itself turned out to
  be on `pve`).
- Network: plain LAN bridge (`vmbr0`, untagged, `192.168.1.0/24`) via the
  `lan` attachment already defined in `terraform/lxc/network/pve-test-vm.yaml`
  — no SDN zone, no zone-membership file entries.
- IP: `192.168.1.55/24`. VMID: `50010`.
- Firewall: `pentest_seg → 192.168.1.55`, scoped to exactly TCP 8080 and
  6379 (narrower than Metasploitable2's full-range rule, since this
  target's services are fixed and known in advance — this enforces
  "exactly two services reachable" at the network level, not just by
  what's installed). Documented in `network/pve-test-vm.yaml`'s
  `policies:` block; actual enforcement is a manual MikroTik step, same
  as the existing Metasploitable2 rule.

  **Ordering gotcha hit and fixed live**: the rule was initially appended
  to the end of the `forward` chain, which put it *after* the existing
  `pentest_seg` default-deny catch-all (`chain=forward action=drop
  in-interface=vlan70-pentest`) — making it a dead rule despite being
  present and correctly written. The Metasploitable2 rule works only
  because it sits *before* that catch-all. Fixed by moving the new rule
  to just before the catch-all (`/ip firewall filter move <n>
  destination=<catch-all-position>`). Any future destination-scoped
  `pentest_seg` rule needs the same placement check — a rule existing
  and being correctly written doesn't mean it's reachable; check its
  position relative to the zone's own default-deny rule.
- Implementation: `terraform/lxc/stacks/harness-target/` (`stack.yaml`,
  `docker-compose.yml`, `STACK_CONTRACT.md`),
  `terraform/lxc/environments/pve-test-vm/harness-target/terragrunt.hcl`,
  `terraform/lxc/ansible/playbooks/deploy-harness-target.yml`. Scaffolded
  via `terraform/lxc/scaffold-stack.sh harness-target`.

## Verified live (2026-07-30)

- Struts2 S2-045 header-injection PoC (`233*233` reflected via an
  injected response header): confirmed, `54289` returned exactly.
- Struts2 full RCE via the standard `ProcessBuilder` OGNL payload:
  confirmed, `id` returned `uid=0(root) gid=0(root) groups=0(root)`.
- Redis unauthenticated network access (raw RESP protocol, not
  `docker exec`): confirmed, `PING` → `PONG`, `GET internal:api_key` →
  the seeded marker value.
- Idempotency: re-ran `provision.sh --stack harness-target` a second
  time with no manual cleanup in between — both services came back
  healthy and the marker key was still retrievable, confirming the
  "no reset needed between tests" requirement actually holds.
- Firewall reachability from `pentest_seg` (the `pentagi-stack` host):
  both TCP 8080 and 6379 confirmed open after fixing the rule-ordering
  gotcha above.
- Regression check: every one of `pentagi-stack`'s own pre-existing
  network dependencies (infra_seg Harbor/apt-cacher, framework Ollama/
  SearXNG/llamacpp-router, Metasploitable2, Harbor via Traefik/edge_seg)
  re-tested reachable after the reorder — expected, since the reorder
  only repositioned the brand-new rule relative to the zone's catch-all
  and never touched the relative order of any pre-existing rule.

## Two scaffolder bugs found and fixed while standing this up

Both were pre-existing issues in `terraform/lxc/`'s shared scaffolding
tooling, unrelated to this stack specifically, but blocked or would have
broken it:

1. `validate-stack-metadata.py` and `validate-compose.py` both hardcoded
   `minecraft-stack` in their `ACTIVE_STACKS` list even though it was
   only ever planned (Stage 10, per `docs/stack-lifecycle-refactor/`)
   and never actually built — its directory has never existed. This
   broke `scaffold-stack.sh` for any new stack, not just this one. Fixed
   by removing the stale entry from both files.
2. The scaffolder's `terragrunt-writer` step produces the legacy
   `terraform/lxc/stacks/<name>/terragrunt.hcl` layout by default, but
   comparing actual state-file modification times across existing
   stacks (e.g. `harbor-stack`'s legacy-location state last touched
   2026-05-30 vs. its environment-scoped copy at 2026-06-24; `pentagi-stack`'s
   environment-scoped state at 2026-07-26) confirms the environment-scoped
   layout (`terraform/lxc/environments/<node>/<stack>/`) is the actually
   current convention. Moved the generated `terragrunt.hcl` there by hand
   for this stack; the scaffolder itself still needs fixing for future
   stacks (not done here — out of scope for this task).
