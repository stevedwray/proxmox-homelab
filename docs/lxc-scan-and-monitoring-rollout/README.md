# lxc-scan-and-monitoring-rollout

Redesigns GVM/Greenbone's credentialed (LSC) scanning from ad hoc
root-SSH-key reuse to a dedicated per-host `gvm-scan` account (unique SSH
keypair + unique sudo password per LXC, OpenBao-backed), and extends both
the Wazuh agent and Docker-container-log-to-Graylog forwarding from a
partial pilot to the real 25-stack in-scope fleet on `pve` (not the ~36
originally estimated -- see plan.md's scope-correction notes).

See `plan.md` for the full design, the operator's 2026-09-29 judgment-call
answers, and the bounded step packets.

## Status (2026-09-29): Track A fully deployed and verified live; Track B not started

### Track A -- GVM credentialed scanning: DONE

- `gvm-03` (secrets/manifest.json, 25 entries) done by the operator; `gvm-04`
  bootstrap run and verified (all 25 stacks' keypairs/passwords live in
  OpenBao).
- All 25 in-scope stacks redeployed with the `gvm_scan_account` role
  (dedicated SSH keypair + full sudo, password-gated). Verified live: SSH
  login + sudo elevation both confirmed working via a real credentialed
  probe (`BIOS and Hardware Information Detection (Linux/Unix SSH Login)`
  NVT result, which requires both) against a 2-zone sample
  (`harbor-stack`/infra_seg, `proxy-stack`/edge_seg).
- `greenbone-stack` redeployed: `gvm-07` registered all 25 hosts' login +
  elevate credentials, Targets, and Tasks in GVM. Verified live via an
  idempotent re-run (every object reports "already exists").
- `gvm-08` (added after Track A's initial deploy, operator asked for the
  scans to be organized "by VLAN"): a GVM Target can only carry **one**
  `ssh_credential_id` for every host it contains, in every shipped
  python-gvm/GMP version -- confirmed directly against upstream source,
  not assumed -- so true one-Target-per-zone isn't possible without
  abandoning the unique-credential-per-host design. Implemented instead as
  one GVM **Schedule** per network zone (daily, staggered ~45min apart
  from 01:00 UTC across the 10 in-scope zones) and one **Tag** per zone
  (`zone:<name>`) attached to that zone's tasks, while each host keeps its
  own separate Target/credential. Deployed and verified live: all 10
  schedules created with the right recurrence (`DTSTART`/`RRULE:FREQ=DAILY`
  confirmed via raw GMP XML), all 25 tasks confirmed wired to their zone's
  schedule, all 10 tags confirmed with the right host counts, and `gvmd`'s
  own event log confirms the schedules are live (not silently rejected).
  **First real unattended scan**: tonight, `mgmt_seg` at 01:00 UTC (the
  largest zone, 7 hosts) -- not yet observed completing; the credentialed
  probe above stopped its 2 sample tasks early on purpose (it's a
  credential check, not a full scan), so no zone has finished a real
  "Full and fast" run under the new schedule yet. Worth checking report
  counts after 2026-09-30 08:00 UTC (all 10 zones' first run will have
  passed by then).

Real bugs found and fixed live during this rollout (all on
`task/lxc-scan-and-monitoring-rollout-plan`, commits `07bbdffc`
through `16005dcf`):

- `gvm-05`/`gvm-07`'s `delegate_to: localhost` OpenBao-read tasks
  inherited the enclosing play's `become: true`, so `sudo` stripped
  `LAB_IP_OPENBAO`/`OPENBAO_ADDR` from the environment -- fixed with
  `become: false` on those specific tasks, across all 25 playbooks plus
  `greenbone-stack`'s fleet-targets generation.
- An unrelated pre-existing bug in `gaming-stack-lab`'s Wings DNS-fix task
  (`replace: '\1{{ dns_server }}'` -- Python's `re.sub` parses `\1`
  immediately followed by a digit as a two-digit group reference) blocked
  that stack's redeploy; fixed with `\g<1>`.
- python-gvm has **no** parameter for an SSH elevate/privilege-escalation
  credential on `create_target`/`modify_target`, in any shipped GMP
  version (v224 through v227/next -- checked upstream source directly).
  GMP's raw protocol does support it (`<ssh_elevate_credential id="..."/>`,
  confirmed against Greenbone's own GMP schema docs and forum). Worked
  around by hand-building the request via the same internal
  `Targets.create_target()` builder `gmp.create_target()` itself uses,
  appending that element, and sending it through
  `gmp._send_request_and_transform_response()`.
- Used the wrong node-secrets wrapper (`./with-secrets-prod` instead of
  `./with-secrets-prod-tiny`) for `ai-services-stack`, `mcp-utility-stack`,
  `opensearch-stack` on the first pass -- caught before it mattered
  (both inventories resolve to the same `ansible_host`, so nothing was
  misapplied) and re-run correctly.

### Track B -- Wazuh + Graylog: NOT STARTED

No blockers. `waz-01`/`waz-02`/`log-01`/`log-02` are code-complete
(see plan.md) but nothing has been redeployed with Track B active --
every Track A redeploy above used `ANSIBLE_SKIP_TAGS=wazuh_agent_rollout`
(added this session -- every Wazuh-enrollment play/role inclusion across
all 25+ playbooks is now tagged `wazuh_agent_rollout` specifically so
Track A and B can be rolled out independently) because a real, unrelated
Wazuh-manager-API timeout surfaced on `ai-services-stack` mid-rollout and
the operator asked to defer Track B rather than debug it inline.

**Next steps for Track B**, whenever picked up:

1. Diagnose the `ai-services-stack` → Wazuh-manager-API timeout (port
   55000, `ai_seg` → `infra_seg` zone crossing) before re-attempting --
   this is a real, not-yet-understood failure, not the "unverified against
   a live manager" risk originally flagged for `waz-01`'s group-creation
   call (that part never got far enough to be tested).
2. Redeploy the 25 in-scope stacks without `ANSIBLE_SKIP_TAGS` (or with it
   unset) to pick up `wazuh_agent`/`wazuh_agent_group`, plus for
   `ai-services-stack`/`mcp-utility-stack` specifically the `docker_base`
   log-driver migration (`log-02`).
3. Canary suggestion: something in a zone with an already-working manager
   path, not `ai_seg` again until the timeout is understood.

## Known, deliberate gaps (not bugs -- documented, not silently dropped)

- `media-stack`, `management-stack`, `omada-controller`,
  `proxmox-backup-server` are all real, running stacks on `pve`
  (confirmed via a live Proxmox API call) with **no Ansible playbook in
  this repo at all** -- can't join this rollout until one exists. See
  the comment above `IN_SCOPE_STACKS` in
  `scripts/gvm_fleet_targets_generate.py`.
- `pentagi-stack` (CTs confirmed destroyed 2026-09-28) and
  `pentagi-upstream-control` (a comparison baseline, not real
  production) are deliberately excluded.
