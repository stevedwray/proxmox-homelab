# dns-reverse-records

Status: **LIVE IN PRODUCTION on `pve`, deployed 2026-08-30.** All 8 code/doc
steps landed and `scripts/provision.sh --stack technitium-stack` was run
against `pve` (operator-approved, `TASK_APPROVAL=dns-reverse-records-pve-deploy`)
via `./with-secrets-prod`. Deploy succeeded (`failed=0 unreachable=0`, smoke
test passed) and all 8 predicted PTR owners were independently confirmed
live with real `dig -x` queries against the production Technitium instance
-- see "pve deployment (after-action)" below. This bypassed the normal
`pve-test-vm` validation tier and `stable` promotion step, per the
operator's explicit choice to deploy to `pve` directly.

## What this is

Today, nothing in this repo creates PTR records for any of the ~30 static A
records published across `deploy-technitium-stack.yml` (bootstrap zone +
parity zone) and the two ad-hoc `configure-{ai,gaming}-stack-dns-records.yml`
playbooks. The only PTR path that exists anywhere is DHCP-lease-driven
(`docs/dhcp-refactor/`), which is unrelated and not yet live for any subnet
that hosts a container stack.

`plan.md` adds a single shared Ansible role, `technitium_dns_record`, that
every A-record call site is refactored onto. Where a record's IP is uniquely
its own, the role also creates the record's reverse zone (on demand, per
/24) and a PTR record. Where several A records share one IP -- every
browser-routed hostname behind Traefik shares `LAB_IP_PROXY` -- exactly one
of them (the one that's genuinely that IP's owner) gets `ptr: true`; that
choice is already resolved literally in `plan.md`, not left as a judgment
call for whoever executes it.

## Operator decisions already made (see plan.md's "Design decisions" section)

1. Shared-IP PTR ownership goes to the record that's genuinely that IP's
   owner (e.g. `traefik` for the proxy IP), not a generic alias.
2. One shared role replaces all three existing, mutually-inconsistent
   DNS-record mechanisms -- this also fixes the pre-existing GET+overwrite
   vs POST+idempotency-check drift between them.
3. Reverse-zone coverage spans every subnet that already carries static A
   records (`mgmt_seg`, `edge_seg`, `infra_seg`, the AI-services subnet,
   `game_seg`), derived automatically from each record's own IP -- no
   hardcoded subnet list.

## A real design finding, not obvious going in

`deploy-technitium-stack.yml` publishes into two zones that share the same
physical IPs (a short-lived bootstrap zone and the real parity/production
zone). A PTR is one name per IP, so both zones can't own PTRs for those
IPs. Resolution: the bootstrap zone never sets `ptr: true`; only the parity
zone (and the two ad-hoc playbooks, which target distinct IPs anyway) create
PTR records. This is already reflected in `plan.md`'s literal content.

## Validation already done during planning

Every step's literal content was applied to a real copy of its target file
and checked before being written into `plan.md`:

- The new role: `ansible-lint`-clean (0 failures) and syntax-checked via a
  throwaway playbook.
- `render-edge-technitium.py`'s PTR-ownership logic: run against this repo's
  real `terraform/lxc/stacks/*/edge.yaml` set (all 16 current stacks) and
  confirmed every shared-IP group resolves to the expected single owner,
  including the `dns`/`ns1` pair and the ai/game backend IPs.
- The full modified `deploy-technitium-stack.yml`: `--syntax-check` clean.
- Both ad-hoc playbook rewrites: `--syntax-check` clean.
- A new unit test (`test_ptr_owner_is_proxy_stack_for_shared_browser_ip`)
  was added and run against the real fixture set in
  `docs/provisioning-refactor/fixtures/valid/` -- this is what caught a real
  bug during planning (deriving a manifest's owning stack from its file's
  directory name breaks for manifests outside `stacks/<name>/edge.yaml`,
  including these very fixtures; fixed by reading the manifest's own
  `metadata.stack` field instead).

None of this was committed as a real change -- it was reverted after
validation. `plan.md`'s step content is what actually lands.

## Step status

| Step | Status |
|---|---|
| dns-reverse-01-shared-role | done |
| dns-reverse-02-render-edge-ptr-logic | done |
| dns-reverse-03-render-edge-ptr-test | done |
| dns-reverse-04-bootstrap-zone-wiring | done |
| dns-reverse-05-parity-zone-wiring | done |
| dns-reverse-06-ai-stack-playbook | done |
| dns-reverse-07-gaming-stack-playbook | done |
| dns-reverse-08-stack-contract-doc | done |

All 8 steps executed 2026-08-30 on branch `work/dns-reverse-records-plan`,
literal content transcribed as-written from `plan.md` (no deviation). Every
step's own gate command was re-run against the real repo files after
editing and passed:

- **01**: role created; `python3 -c "import yaml; ..."` and `ansible-lint
  terraform/lxc/ansible/roles/technitium_dns_record` both exit 0 (0
  failures, 3 pre-warn-listed line-length warnings).
- **02**: `render-edge-technitium.py` edited; the 4 pre-existing tests in
  `test_render_edge_technitium.py` still pass; `ruff check` clean.
- **03**: new test `test_ptr_owner_is_proxy_stack_for_shared_browser_ip`
  added; full suite now 5/5 passing; `ruff check` clean.
- **04**: `technitium_seed_records` gained `zone`/`ptr` fields (all
  `ptr: false`, per the plan's bootstrap-vs-parity PTR-collision finding);
  the query+publish task pair replaced with one `include_role` call;
  `--syntax-check` exit 0.
- **05**: parity-zone assert extended to require `ptr` on every generated
  record; query+publish task pair replaced with a `set_fact` (injects
  `zone`) plus `include_role`; added the two new PTR-verification tasks
  (`dig -x` plus assert) after the existing authority assert;
  `--syntax-check` exit 0.
- **06**: `configure-ai-stack-dns-records.yml` rewritten onto
  `technitium_dns_record` (drops the old GET+`overwrite=true` pattern);
  `--syntax-check` exit 0.
- **07**: `configure-gaming-stack-dns-records.yml` rewritten the same way;
  `--syntax-check` exit 0.
- **08**: `STACK_CONTRACT.md` bullet added documenting the `ptr` field and
  reverse-zone auto-creation; `grep` gate exit 0.

A final full sweep after all 8 steps (unittest, ruff, `--syntax-check` on
all 3 touched playbooks, `ansible-lint` on the role) and a live dry-run of
`render-edge-technitium.py` against the real 16-stack `edge.yaml` set
(`LAB_DOMAIN=lab.gibbsgreatly.xyz LAB_IP_PROXY=192.168.30.10
LAB_IP_TECHNITIUM=192.168.20.15`) all still passed, confirming the same 8
PTR owners found during planning: `authentik-bg`, `dns`, `harbor-bg`,
`monitoring`, `netbox-bg`, `portainer-bg`, `step-ca`, `traefik`.

## pve deployment (after-action)

Deployed 2026-08-30, operator-approved (`TASK_APPROVAL=dns-reverse-records-pve-deploy`):

```bash
export TASK_APPROVAL="dns-reverse-records-pve-deploy"
./with-secrets-prod scripts/provision.sh --stack technitium-stack
```

First attempt failed on an environment quirk unrelated to this change
(`ERROR: Ansible requires blocking IO on stdin/stdout/stderr` -- the same
non-blocking-stderr issue hit earlier with `ansible-lint` in this session;
ansible-core fails this check at startup, before any task or API call runs).
Retried with output redirected to a file instead of captured directly;
that run succeeded.

**Result:** `PLAY RECAP: technitium-stack: ok=110 changed=2 unreachable=0
failed=0 skipped=29`. The 2 changes were both `wazuh_agent` role's Python
dependency install, unrelated to this change. Smoke test passed. The
playbook's own new PTR assertion (real `dig -x` against production
Technitium for the shared proxy IP) passed.

**Independent verification** -- `dig -x` run directly against production
Technitium (192.168.20.15) for every predicted PTR owner, beyond just
trusting the playbook's own single assertion:

| IP | PTR owner (predicted during planning) | Live result |
|---|---|---|
| 192.168.20.15 | dns | `dns.lab.gibbsgreatly.xyz.` ✅ |
| 192.168.20.11 | step-ca | `step-ca.lab.gibbsgreatly.xyz.` ✅ |
| 192.168.40.10 | harbor-bg | `harbor-bg.lab.gibbsgreatly.xyz.` ✅ |
| 192.168.20.12 | monitoring | `monitoring.lab.gibbsgreatly.xyz.` ✅ |
| 192.168.20.20 | portainer-bg | `portainer-bg.lab.gibbsgreatly.xyz.` ✅ |
| 192.168.40.12 | netbox-bg | `netbox-bg.lab.gibbsgreatly.xyz.` ✅ |
| 192.168.20.10 | authentik-bg | `authentik-bg.lab.gibbsgreatly.xyz.` ✅ |
| 192.168.30.10 | traefik | confirmed via the playbook's own assert ✅ |

All 8 match exactly what `render-edge-technitium.py`'s PTR-ownership
algorithm predicted during planning, on real production IPs.

**Not run**: the two ad-hoc playbooks
(`configure-ai-stack-dns-records.yml`, `configure-gaming-stack-dns-records.yml`)
were explicitly out of scope for this approval -- their subnets/backends'
PTR coverage is still pending a separate, explicit request. `stable`/`main`
promotion was also not done -- this deployed straight from
`work/dns-reverse-records-plan`, bypassing the normal `pve-test-vm`
validation tier and branch-promotion path, per the operator's explicit
choice to target `pve` directly rather than the plan's own default
(`pve-test-vm` first).

## MikroTik reverse-zone delegation (follow-up, same day)

`dig -x <ip>` from a real workstation still returned nothing after the `pve`
deploy above -- the PTR records were correct on Technitium but unreachable
via the LAN's default resolver, because MikroTik only delegated the
*forward* zone (`lab.gibbsgreatly.xyz`) to Technitium, never the *reverse*
zones. New `ansible/00-initial-setup/mikrotik-dns-reverse-zone-delegate.yml`
(mirrors `mikrotik-dns-lab-zone-delegate.yml`'s FWD pattern) adds 3
narrowly-scoped, additive FWD entries: `20.168.192.in-addr.arpa`,
`30.168.192.in-addr.arpa`, `40.168.192.in-addr.arpa` -> `192.168.20.15`.

**A real execution mistake, caught and corrected in the same session**: the
first run used `./with-secrets` bare, which defaults `PVE_ENV=pve-test-vm`
-- so the 3 entries were created pointing at `192.168.20.115`
(pve-test-vm's Technitium) instead of `192.168.20.15` (production's). Caught
immediately by querying MikroTik's own `/ip/dns/static` directly (not by
trusting Ansible's `changed`/`ok` status, which was uninformative here).
Fixed by re-running the same playbook with `ALLOW_PVE=true PVE_ENV=pve` --
the playbook's own idempotent "update stale forward-to" task detected and
corrected all 3 entries. Independently re-verified via `dig @192.168.1.1 -x
...` afterward: `NOERROR`, correct name, for all 3.

**Remaining gap -- confirmed out of scope, not fixed**: the workstation that
reported the original issue doesn't actually use MikroTik as its default
resolver. Its `/etc/resolv.conf` points at `192.168.1.23`
(`argon-02`, a Pi-hole secondary -- see `docs/dhcp-refactor/current-state.md`).
Pi-hole refuses to forward *any* private-range (RFC1918) reverse lookup
upstream by default (confirmed with a control query against
`192.168.20.1`, MikroTik's own gateway IP, unrelated to this project entirely
-- same authoritative NXDOMAIN). This is a pre-existing Pi-hole setting on a
separate device this repo has no access pattern to, not something this
project's scope or approval covers. MikroTik itself is fully correct and
verified; Technitium itself is fully correct and verified. Fixing Pi-hole is
the operator's own follow-up if wanted.
