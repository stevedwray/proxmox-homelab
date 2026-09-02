# CVE remediation runbook

Operational counterpart to Phase 11 (`plan.md`'s Phase 11 section covers
how this was built). This doc is for a future session (or the operator
directly) picking up the weekly output and actually acting on it — it
does not describe how the pipeline works internally.

## Where the recommendations live

`cve_deep_dive.py` runs weekly (Sundays 23:00 UTC) on `secpipe-stack` and
writes one document per shortlisted CVE into OpenSearch's
`cve-remediation-assessment` index — the worst/most-exploitable CVEs
currently in the environment (KEV-listed or a known PoC exists, actually
present in production), each with a `recommended_action` and a concrete
`assessment`.

**To review**: open the "Top CVEs Needing Attention" panel on the
`Threat & Vulnerability Overview (UVM)` Grafana dashboard
(`monitoring-stack`). It's sorted by risk score, highest first, and only
shows CVEs that haven't been marked resolved yet (see below).

## Working through the list

For each row, top to bottom:

1. Read the `assessment` text — it already accounts for this CVE's real
   network zone, containment, and edge/auth exposure, not generic advice.
2. Act according to `recommended_action`:
   - **PATCH** / **UPGRADE** — the fix is a version bump or vendor patch.
     Find the affected stack's own `deploy-<stack>.yml` playbook and
     `stack.yaml` image tag, bump it, redeploy per that stack's own
     validation tier in the top-level `CLAUDE.md` (most container image
     bumps are a normal `provision.sh --stack <name>` run, not a full
     teardown).
   - **ISOLATE** — tighten the affected zone's MikroTik firewall rule
     (see `ansible/00-initial-setup/mikrotik-firewall-*.yml` for the
     existing pattern) rather than waiting on a patch, when one isn't
     available yet or can't be applied immediately.
   - **ACCEPT_RISK** — a deliberate decision that the exposure is
     acceptable given containment (e.g. an internal-only zone, no real
     exploit path). Still requires a `--note` explaining why when marking
     it resolved (see below) — an accepted risk with no recorded reason
     is indistinguishable from one nobody looked at.
   - **INVESTIGATE** — the model didn't have enough signal to commit to
     one of the other four calls. Look at the underlying finding
     yourself (the CVE's full `unified-cve-exposure` document has the raw
     `triage_raw_text` from `cve-mcp-server`) before deciding.
3. Once the action is actually taken (or the risk deliberately accepted),
   mark it resolved (below) so it drops off the panel and doesn't come
   back next week for no reason.

## Marking a CVE resolved

On `secpipe-stack`:

```bash
ansible all -i "<secpipe-stack IP>," -u root -m shell \
  -a "cd /opt/cve-enrichment-sync && set -a && . ./es-user.env && set +a && \
      python3 mark_cve_resolved.py CVE-XXXX-XXXXX \
        --elasticsearch-url https://<opensearch-stack IP>:9200 --no-verify-tls \
        --note 'Upgraded wazuh-manager to 4.15.2 on 2026-09-10'"
```

(`ansible`'s `shell` module runs `/bin/sh`, not bash — plain `source` isn't
available there, hence `. ./es-user.env`. `--elasticsearch-url` is
required explicitly: the systemd service sets it via `Environment=`, but
`es-user.env` itself only carries the OpenSearch credential.)

`--note` is required (except for `--reopen`) — it's what makes an
`ACCEPT_RISK` call reviewable later, and what tells a future session what
was actually done for a `PATCH`/`UPGRADE`/`ISOLATE` call.

To undo a mistaken resolution: same command with `--reopen` instead of
`--note`.

### Why resolved CVEs can still reappear

`cve_deep_dive.py` only carries a `resolved` flag forward to its next
weekly run if the CVE's `risk_score` hasn't changed since it was marked
resolved. If the score *has* changed — new instances showed up, or the
underlying triage data shifted — the CVE reappears on the panel
unresolved, on purpose: something material changed, so the earlier
resolution no longer has enough context to keep trusting it silently.
This is a deliberate blind spot in the *automatic* carry-forward (a
resolved flag never auto-expires just from time passing) — resolving
something quiets it only for stable numbers.

## Where the raw data lives, if you need to go deeper

- `cve-remediation-assessment` — the assessments themselves (this
  runbook's own scope).
- `unified-cve-exposure` — the correlated CVE record each assessment was
  built from (`triage_raw_text`, `cvss_vector`, `epss_score`, per-source
  breakdown in `sources[]`).
- `stack-risk-summary` — the per-stack severity rollup (Phase 9), useful
  for "which stack should I be worried about generally," not
  CVE-by-CVE.

A reminder from Phase 11's own build (see `plan.md`): `sources[].source`
records which **scanner** found a CVE (e.g. `"harbor"` means Harbor's own
registry scanner found it in an image it scanned), not which
**application** is vulnerable — trust the `stacks` field for that, not
the scanner name.
