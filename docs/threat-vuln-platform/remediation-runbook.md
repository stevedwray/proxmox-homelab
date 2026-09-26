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

### `ACCEPT_RISK` blocked on an upstream fix: use `--review-after-days`

A real patch/upgrade only needs the plain `--note` above — a changed
`risk_score` is the right signal to reopen it (see below). But an
`ACCEPT_RISK` made specifically because **no upstream fix exists yet**
(confirmed 2026-09-07: `wazuh-stack`'s `golang.org/x/crypto`/
`k8s.io/apimachinery`/`handlebars` CVEs — none tracked in Wazuh's own
dependency-update changelog across every 4.14.x release) is different:
`risk_score` may never change on its own, so the CVE would stay silently
resolved forever even after upstream ships a fix nobody went looking
for. Add `--review-after-days N` (e.g. `30` for "revisit in a month") to
force it back onto the panel after that many days regardless of score,
so a future session (or the operator) does a real check for an upstream
fix rather than trusting an assumption that's gone stale:

```bash
python3 mark_cve_resolved.py CVE-XXXX-XXXXX \
  --elasticsearch-url https://<opensearch-stack IP>:9200 --no-verify-tls \
  --note "ACCEPT_RISK: no upstream fix yet, see docs/threat-vuln-platform/plan.md" \
  --review-after-days 30
```

### Why resolved CVEs can still reappear

Two independent triggers, both handled the same way by
`cve_deep_dive.py`'s `upsert_assessment()` — the carry-forward simply
stops applying and the CVE reappears unresolved:

1. **`risk_score` changed** since it was marked resolved — new instances
   showed up, or the underlying triage data shifted. Something material
   changed, so the earlier resolution no longer has enough context to
   keep trusting it silently.
2. **`resolved_review_after` has passed** (only set when
   `--review-after-days` was used) — a bounded, time-triggered recheck
   for an `ACCEPT_RISK` that was never going to un-resolve itself on
   score alone.

A plain resolution (no `--review-after-days`) still never auto-expires
from time passing alone — that remains correct for an actual
patch/upgrade, where the score is the only signal that matters.

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
