# dns-reverse-records

Status: **planned, not started.** `plan.md` is a fully researched, fully
validated step-by-step plan (per `docs/agent-design/`) for giving every
statically-published Technitium A record a matching reverse (PTR) record,
where one can meaningfully exist. No step has been executed yet.

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
| dns-reverse-01-shared-role | not started |
| dns-reverse-02-render-edge-ptr-logic | not started |
| dns-reverse-03-render-edge-ptr-test | not started |
| dns-reverse-04-bootstrap-zone-wiring | not started |
| dns-reverse-05-parity-zone-wiring | not started |
| dns-reverse-06-ai-stack-playbook | not started |
| dns-reverse-07-gaming-stack-playbook | not started |
| dns-reverse-08-stack-contract-doc | not started |

(`implement-step` writes each step's hand-back here as it runs -- the actual
edit made and the actual gate results. If a hand-back is missing after a
step supposedly ran, verify it directly rather than trusting a chat reply;
see `docs/agent-design/README.md`.)

## After all steps land

See `plan.md`'s "Not a step -- operator-run validation and promotion"
section: `scripts/provision.sh --stack technitium-stack` on `pve-test-vm` is
the real gate (per CLAUDE.md's Validation Tiers, this is an Ansible
task/role change, not a full teardown), followed by the normal
`feat/* → stable → main` promotion path.
