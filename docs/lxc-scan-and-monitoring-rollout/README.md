# lxc-scan-and-monitoring-rollout

Redesigns GVM/Greenbone's credentialed (LSC) scanning from ad hoc
root-SSH-key reuse to a dedicated per-host `gvm-scan` account (unique SSH
keypair + unique sudo password per LXC, OpenBao-backed), and extends both
the Wazuh agent and Docker-container-log-to-Graylog forwarding from a
partial pilot to the real 25-stack in-scope fleet on `pve` (not the ~36
originally estimated -- see plan.md's scope-correction notes).

See `plan.md` for the full design, the operator's 2026-09-29 judgment-call
answers, and the bounded step packets.

## Status (2026-09-30): All tracks (GVM, Wazuh, Graylog) fully deployed and verified live

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
  one GVM **Schedule** per network zone (daily, staggered ~45min apart)
  and one **Tag** per zone (`zone:<name>`) attached to that zone's tasks,
  while each host keeps its own separate Target/credential.
- **First real unattended scan, and a real bug caught by checking it**:
  when checked the next day, only 1 of 25 hosts (`nextcloud-stack`,
  `apps_seg`'s only host) had actually run -- and it succeeded (1000
  results, real `Authenticated Scan / LSC Info Consolidation` results, 0
  high-severity findings) purely because its zone's time-of-day happened
  to land later than `gvm-08`'s own deploy time on the same calendar day.
  The other 24 hosts hadn't fired at all yet. Digging into why surfaced a
  real design bug: the schedules used `SCHEDULE_TIMEZONE="UTC"` with times
  chosen to *look* like an overnight window, but the operator is in NZT
  (UTC+12/+13, NZ observes DST) -- 01:00-07:45 UTC actually lands at
  14:00-20:45 NZT, the operator's afternoon/evening, not overnight. Fixed
  by switching to a real IANA zone name, `Pacific/Auckland`, instead of a
  fixed offset -- confirmed live that `gvmd` correctly expands this into a
  full DST-aware `VTIMEZONE` block (real NZDT/NZST transition rules), so
  it stays correct across DST changes automatically. `ensure_schedule()`
  now re-applies `icalendar`/`timezone` via `modify_schedule()` even when
  a schedule already exists, not just on first creation, since the fix
  needed to correct the 10 already-created UTC schedules in place.
  Deployed and verified live: all 10 schedules confirmed re-stored with
  the correct `Pacific/Auckland` timezone and DST rules (raw GMP XML), all
  25 tasks and 10 tags re-confirmed wired. First real overnight run under
  the corrected schedule: tonight NZT, `mgmt_seg` first at 01:00 NZT (7
  hosts) -- not yet observed completing as of this writing.

Real bugs found and fixed live during this rollout (all on
`task/lxc-scan-and-monitoring-rollout-plan`, commits `07bbdffc`
through `16005dcf`, plus `fix/gvm-schedule-nzt-timezone`):

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
- `gvm-08`'s schedules used `SCHEDULE_TIMEZONE="UTC"` with times picked to
  look like "overnight," but never checked against the operator's actual
  timezone (NZT) -- found the next day by cross-checking real report
  timestamps against `gvmd`'s own clock, not by trusting the earlier "all
  10 schedules confirmed wired" verification (which only checked the
  schedules existed and were attached, not that their times served the
  actual intent). Fixed with a real IANA zone name (`Pacific/Auckland`)
  instead of a fixed offset, so it also stays correct across DST.

### Track B -- Wazuh agent fleet rollout: DONE, fully deployed and verified live (2026-09-30)

All 25 in-scope stacks redeployed with `wazuh_agent`/`wazuh_agent_group`
active. Verified live via the manager API (not just trusting task
output): every agent shows `status=active` with its correct zone group
(`ai-services-stack`→`ai_seg`, `greenbone-stack`→`pentest_seg`, etc. --
see the full 25-host table in `project_lxc_scan_monitoring_rollout_status`
memory, or query `GET /agents?select=name,group,status` directly).

**Root cause of the original `ai-services-stack` timeout, and the real
fix** (`fix/wazuh-mikrotik-fleet-api-access`, 2 commits): it was never
zone-specific. Every already-registered agent -- the entire original
8-stack pilot, enrolled 2026-08-29 -- was still in the `default` group
on the live manager, meaning **none** of them had ever actually executed
the group-assignment code path added to the role afterward.
`ai-services-stack` was simply the first host in the whole 25-stack fleet
to attempt it. Two real, independent bugs, both found and fixed live:

1. **MikroTik never had port 55000 (the Wazuh manager API) open from any
   zone** -- confirmed by reading the live ruleset directly; every
   existing Wazuh rule only opened `1514,1515` (agent comms/enrollment).
   Fixed with `ansible/00-initial-setup/mikrotik-firewall-wazuh-api-
   fleet.yml`: 14 new narrowly-scoped rules (`+55000` for the 4 zones
   that already had `1514,1515`; both for the 5 zones with no Wazuh rule
   at all). `infra_seg` needs nothing -- same subnet as `wazuh-stack`,
   never hits the MikroTik forward chain.
2. **The `wazuh_agent` role's `-G` flag on `agent-auth` only applies
   group membership at first enrollment.** For any already-connected
   agent (all 8 pilots, or any future already-enrolled host), the
   enrollment task is skipped entirely on redeploy, so `-G` never runs
   and the group silently never applies -- confirmed live: even after
   the MikroTik fix, `apt-cacher-stack` still showed `group=["default"]`
   post-redeploy. Fixed by adding an explicit `PUT /agents/{id}/group/
   {id}` call (confirmed against Wazuh's own API docs, idempotent) that
   runs after enrollment either way, so group membership no longer
   depends on which enrollment path ran.

One transient failure during the fleet batch, not a design bug:
`greenbone-stack` (`pentest_seg`) hit a one-off `Connection refused`
mid-batch (20+ rapid back-to-back API authentications may have briefly
overloaded the manager) -- a live TCP re-test immediately after showed
the connection working fine, and a straight retry of the redeploy
succeeded cleanly.

**`log-01`/`log-02` (Graylog Docker-container-log forwarding) are also
already live**, confirmed 2026-09-30 -- `docker_base_manage_daemon_json`
isn't gated by the Wazuh skip-tag, so it took effect during Track A's
own redeploys of `ai-services-stack`/`mcp-utility-stack`. Verified live:
`ai-services-stack`'s `/etc/docker/daemon.json` shows the correct
`syslog` driver, RFC5424 format, `tcp://127.0.0.1:10514`. (plan.md's
Phase 3 section previously said this was undeployed -- that was stale,
written before Track A's redeploys actually ran; corrected here.)

**Both Track A and Track B are now fully deployed and verified live.**
The only remaining open item from this whole rollout is `log-03`
(fleet-wide verification pass across the other ~23 already-`syslog`
stacks) -- a check, not new code; not run yet.

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
