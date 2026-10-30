# Alert investigator: ask the local model to triage an alert

Status 2026-10-30: **built and unit-tested, not deployed.** Branch `ccr-f6c779fd-ufumqp`. 37 new tests (no network) plus an
end-to-end run against local stub servers (model, Grafana, VictoriaMetrics, Discord upload). Never yet run against the real
Framework model or the lab's real data. Deploying it means re-running the silence bot's playbook (below).
Parent docs: [README.md](README.md), [discord-silence-bot.md](discord-silence-bot.md).
Code: `terraform/lxc/ansible/files/alert_investigator.py` (the investigation), `discord_silence_bot.py` (trigger, queue,
reply). Playbook: `terraform/lxc/ansible/playbooks/deploy-discord-silence-bot.yml`.

## What it does

You react 🔍 to an alert in Discord. A few minutes later the bot replies in the thread with a verdict and attaches the full
write-up:

> 🟠 **needs-attention**: node_exporter on portainer exited after the cert-renewal SIGHUP; host is fine, metrics are missing.
> -# 6 tool call(s), model `glm-5.3-flash-upstream`, 142s. Advisory only: nothing was changed.
>
> 📎 investigation-20261030-0812.md

The attached report has the sections *What fired*, *Evidence*, *Likely cause*, *Suggested next steps* and *Confidence*,
then every tool call the model made, with the output it saw, so you can check its reasoning.

Verdicts: 🔴 `real-problem`, 🟠 `needs-attention`, ⚪ `noise`, ❔ `unclear`.

### Triggers (operator decisions, 2026-10-30)

| Trigger | When |
|---|---|
| 🔍 (or 🔎) from you on any Grafana alert message | Always, within 24 hours of the message |
| **A page arriving** (labels `page=true` or `tripwire=honeypot`) | Automatically, if the message is under an hour old. Once per alert per 12 hours: a page repeats every 30 minutes and is not re-investigated each time |

Change the automatic labels with `INVESTIGATE_AUTO_LABELS` (empty turns automatic runs off).

### Markers the bot adds

| Marker | Meaning |
|---|---|
| ⏳ | Queued or running |
| 📝 | Done; the reply is in the thread |
| ⚠️ | Failed (the reply says why), or nothing to investigate |

These are separate from the silence markers (✅ ❌): you can investigate an alert and still silence it with 👍, in either order.
After a restart, a message with ⏳ and no 📝/⚠️ is picked up again.

## How it works

1. The poll loop (every 30 s, as for silences) spots the trigger, adds ⏳ and queues a job. It reads each alert's labels from
   the message's silence links, the same way silencing does.
2. One worker thread runs one investigation at a time (queue of 5; a sixth gets ⚠️ "too many queued"). Silencing is never
   held up by the model.
3. The bot gives the model the Discord message, each alert's labels, **the rule behind it** (query, state, firing instances)
   and **everything else firing**, all fetched before the model starts.
4. The model then calls tools, up to **8 rounds** of at most 4 calls each, within **15 minutes**. If it is still calling
   tools at the limit, it is told to stop and write the report.
5. The reply goes to the alert's thread, with the report attached as a Markdown file.

The model is **whatever Framework has loaded** on `:8080` (llama-swap). The bot cannot and does not switch models. The report
names the model it used.

### The tools (all read-only)

| Tool | Reads | Through |
|---|---|---|
| `query_metrics(promql, hours)` | VictoriaMetrics, current value or a window of up to 7 days (min, max, last, a few samples) | `127.0.0.1:8428`, no auth |
| `host_overview(stack)` | up, load, memory, fullest disk, uptime, container restarts for one `stack` label | same |
| `alert_rule(name)` | A Grafana rule's query, labels, state and instances | the bot's existing Grafana token |
| `firing_alerts()` | Everything firing now, including silenced | same |
| `search_logs(query, minutes)` | Graylog, Lucene syntax, up to 24 h and 50 messages, newest first | new Graylog service account (Reader) |
| `harbor_findings(project, repository, severity)` | Harbor image findings: CVE, package, fixed version, in production, in use | new OpenSearch user, `harbor-findings*` |
| `gvm_findings(task, host, min_severity)` | Greenbone results, **never** `pentest_target` ones | same, `gvm-findings*` |
| `cve_context(cve_id)` | EPSS, CISA KEV, public exploit, risk band, where deployed, and the lab's existing deep-dive assessment | same, `unified-cve-exposure*`, `cve-remediation-assessment*` |

The Harbor and Greenbone tools reuse the CVE enrichment the lab already runs (secpipe-stack, `docs/threat-vuln-platform/`),
so a vulnerability alert's triage starts from KEV and EPSS, not from scratch.

Each tool result is cut to 4,000 characters. Text that looks like `password=…`, `token: …`, `Bearer …` or a Discord webhook
URL is replaced with `[redacted]` before the model sees it and again before anything is posted.

## Security

- **It cannot change anything.** Every tool is a fixed GET, or a search POST to one index or endpoint. There is no shell,
  no SSH, no Proxmox API, no write path. A test checks this for every tool.
- **Each source has its own read-only account**, created by the playbook and stored 0600 on the monitoring host:
  a Graylog service account (role Reader, read on every stream except **Pentest Segment**; it cannot log in to the UI) and
  an OpenSearch user with `read` on the four index patterns above only. The bot never holds the Graylog root password or
  the OpenSearch admin password; the play uses them once.
- **Untrusted text.** Log lines and finding descriptions can be written by anyone who can make a service log something.
  The prompt says tool output is data, not instructions, but a local model can still be misled. The consequence is limited
  to a wrong report in your private alert channels. Treat the verdict as a lead, not a fact.
- **What leaves the lab:** the summary and the report go to Discord, like the alerts already do. They can quote log lines
  and finding text. Redaction catches key=value secrets, not every secret shape.
- **The model call** goes to Framework on the LAN with `LLM_GPU_STACK_API_KEY`, the same as the CVE enrichment job.
- **OpenSearch TLS is not verified** (`OPENSEARCH_VERIFY_TLS=false`), matching the lab's existing OpenSearch datasources
  (`uvm_dashboard_es_no_verify_tls`). Turn it on when OpenSearch has a step-ca certificate.

## Setup

**1. Discord: allow the bot to attach files (you, once)**

The bot needs the **Attach Files** permission in each alert channel. Either re-invite it with the new permission set,
`https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot&permissions=101440` (the old 68672 plus Attach Files),
or grant **Attach Files** to the bot's role in each alert channel. Without it the reply still arrives, with the note
"Could not attach the full report".

**2. Secrets:** nothing new. The play uses `LLM_GPU_STACK_API_KEY` (`services/llm-gpu`), `GRAYLOG_ROOT_PASSWORD`
(`services/graylog`) and `OPENSEARCH_ADMIN_PASSWORD` (`services/opensearch`), all already in the `pve` profile.

**3. Deploy** (approval name `alert-investigator`; same hand-run as the silence bot)

Preflight: target the monitoring-stack LXC on `pve` (192.168.20.12). Mutating: creates the `alert-investigator` user in
Graylog and in OpenSearch (plus the `alert_investigator_reader` role), copies one more script, rewrites the bot's `.env`,
raises its memory limit from 128 MB to 256 MB, and recreates the `discord-silence-bot` container. Out of scope:
monitoring-stack itself, Grafana rules and contact points, Framework.

```bash
export ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles
./with-secrets-prod ansible-playbook -i terraform/lxc/environments/pve/monitoring-stack/inventory.yml -u root \
  terraform/lxc/ansible/playbooks/deploy-discord-silence-bot.yml --check --diff    # preview
TASK_APPROVAL=alert-investigator ./with-secrets-prod ansible-playbook \
  -i terraform/lxc/environments/pve/monitoring-stack/inventory.yml -u root \
  terraform/lxc/ansible/playbooks/deploy-discord-silence-bot.yml                   # apply
```

The play ends with the bot's startup line, which should now read
`… grafana healthy=True; investigations on (metrics, grafana, graylog, opensearch)`.
`-e investigator_enabled=false` deploys the silence bot alone, as before.

**4. Prove it**

1. **Manual, harmless:** in Grafana, send a contact-point **Test** to the Discord warning channel and react 🔍. Expect ⏳,
   then within a few minutes a reply, 📝 and an attached report. A test alert has no real rule, so expect `unclear`;
   the point is the plumbing. Then react 👍 to the same message and check the silence still works.
2. **A real alert:** Drill A from the alerting runbook (`docker stop cadvisor` on the monitoring host). When "Scrape target
   down" arrives, react 🔍. A good report finds `up=0` for cAdvisor and says the container is stopped, not the host down.
   Start cAdvisor again.
3. **Automatic on a page:** check that a real page's silence link contains `matcher=page%3Dtrue` (open one in
   `#alerts-critical`, or the bot's log after the next page). The automatic trigger depends on it. If Grafana leaves custom
   labels out of the link, automatic runs never start: report it and the fix is to read labels from Grafana's alert API.
4. **A vulnerability alert:** react 🔍 to the next "New critical vulnerability in a Harbor image". The report should name
   the CVEs, the fixed version, and whether each one is in KEV.

## Operations

- Logs: `docker logs discord-silence-bot` (one line per queued job and per finished one, with its duration).
- A ⚠️ "Investigation failed: … Connection refused / 503" means Framework is down, or busy loading a model or with a
  benchmark. The ⚠️ is final for that message; react 🔍 on the alert's next message to try again.
- Each investigation is a handful of model calls. Framework serves one request per slot, so an investigation running
  during a benchmark slows both. Automatic runs are limited to pages for that reason.
- Tests: `cd terraform/lxc/ansible/files && python3 -m unittest test_discord_silence_bot test_alert_investigator`
  (56 tests, no network).
- Tune with environment variables in `/opt/discord-silence-bot/.env` (add them to the playbook to make them stick):
  `INVESTIGATOR_MAX_STEPS` (8), `INVESTIGATOR_DEADLINE_SECONDS` (900), `INVESTIGATOR_LLM_TIMEOUT_SECONDS` (300),
  `INVESTIGATOR_MODEL` (empty: whatever is loaded), `INVESTIGATE_AUTO_LABELS`, `INVESTIGATE_AUTO_MAX_AGE_MINUTES` (60),
  `INVESTIGATE_AUTO_REPEAT_HOURS` (12).
- Rotate the Graylog token: delete `/opt/discord-silence-bot/graylog-token` and re-run the play (it also replaces a token
  that stops working). OpenSearch password: delete `opensearch-password` and re-run.

## Not verified yet (check during the first deploy)

1. **Graylog 7.1's search API.** The tool uses `POST /api/search/messages` (Graylog's simple search API). The play proves
   the token can search before it finishes, so a mismatch fails the deploy rather than every investigation. Also open:
   whether Graylog honours `token_ttl: P3650D` or caps it; a capped token is replaced by the next play run.
2. **Custom labels in Grafana's silence link** (proof step 3).
3. **Tool calling by the loaded model.** GLM scored 75.5% on BFCL on llama.cpp (`models.json`). A model that ignores the
   tools still produces a report, from the rule and firing alerts it was given up front, with few tool calls listed.
   Check how many tool calls the first reports show.
4. **Time per investigation** on Framework. The budget is 15 minutes; expect two to five.

## Not built (possible next steps)

- Investigating from Telegram (it has no reactions the bot reads; a `/investigate` command would need Telegram polling).
- Container logs straight from a host (`docker logs` over SSH): deliberately left out, since it needs a credential that can
  run commands. Logs the hosts already ship to Graylog are covered.
- A memory of past investigations (e.g. "this fired three times this week, each time noise").
