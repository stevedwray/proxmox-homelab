# Alert investigator: ask the local model to triage an alert

Status 2026-10-31: **live on the monitoring-stack (`pve`, 192.168.20.12)**, proven against the real Framework model
(`glm-5.3-flash-upstream`) with a test alert, a real outage (drill A) and real vulnerability alerts. One proof step waits for a
real page (see "Not verified yet"). Deployed with the silence bot's playbook under approval `alert-investigator`.

**What the proof showed (2026-10-30/31)**

| Step | Result |
|---|---|
| Playbook proof task (Graylog `POST /api/search/messages`) | Passed on Graylog 7.1: the token searched. Whether `token_ttl: P3650D` was honoured was not checked (a capped token is replaced by the next play run). |
| 1. Test alert, 🔍 then 🌙 | Reply and 📝 in 57 s, 4 tool calls, `noise`, 4 KB report attached (so Attach Files works). 🌙 then silenced it as before. |
| First test run | Failed `Name does not resolve` for `framework.gibbsgreatly.xyz`: see Findings. |
| 2. Drill A (`docker stop cadvisor`) | Alert after about 6 min; Telegram silent. Report: `up=0` for the cadvisor target only, host and other services healthy, `container_last_seen` flatlined at the stop time, scrape errors in Graylog; `needs-attention`. 21 tool calls, 407 s, 32 KB report. `[RESOLVED]` arrived about 7 min after the restart. |
| 3. `page=true` in the silence link | Partly: Grafana does put custom rule labels in the link (`severity`, `stack` seen on the cadvisor alert). `page=true` itself needs a real page. |
| 4. Harbor vulnerability alert | Passed (2026-10-31, four "Open critical vulnerabilities" messages): 8 to 10 tool calls, 186 to 198 s, reports name the CVEs with CVSS, EPSS and public-exploit status, say whether a fixed version exists, and separate images in use or in production from unused ones. KEV was not called out in the summaries seen. |

**Findings that differ from the earlier text**

- **The bot must run on a glibc image.** On `python:3.12-alpine` (musl) the lookup of `framework.gibbsgreatly.xyz` failed
  although the host resolved it: the router answers AAAA for that static name with NXDOMAIN, and musl treats that as a failure.
  The playbook now uses `python:3.12-slim`. (The proper fix, an empty AAAA answer on the router, is a production router
  change and was not made.)
- **Steps are rounds, not calls.** `INVESTIGATOR_MAX_STEPS` (8 model rounds, up to 4 tool calls each) counts model rounds; each round may ask for up to 4 tools, so a
  real investigation made 21 calls.
- **Time per investigation:** 57 s for a test alert, about 7 minutes for a real outage, against the expected 2 to 5.
- **Reaction buttons.** The bot now adds 🔍 and 🌙 itself to fresh alerts that have a silence link (alerts under 2 hours old),
  so they are one click, not a hunt through the emoji picker. Its own reaction is not a request. Tune with
  `DISCORD_BOT_SEED_REACTIONS` and `DISCORD_BOT_SEED_MAX_AGE_HOURS`. Clicking a reaction you already made removes it.
- The deploy was run without a `--check --diff` preview: the prod wrapper blocks it without `TASK_APPROVAL`.

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
- **What 🔍 does nothing for:** a **Resolved** message (it has no alert labels, so the bot replies "nothing to investigate"),
  a message older than 24 hours (skipped silently), a channel the bot does not watch, and a post that did not come from a
  Grafana webhook. Only react on a message that is still firing. The bot adds 🔍 and 🌙 itself to fresh alerts that have a
  silence link, so their absence is the sign that a message is not investigable. The queue holds 5 jobs; a sixth gets a final ⚠.
- Each investigation is a handful of model calls. Framework serves one request per slot, so an investigation running
  during a benchmark slows both. Automatic runs are limited to pages for that reason.
- Tests: `cd terraform/lxc/ansible/files && python3 -m unittest test_discord_silence_bot test_alert_investigator`
  (61 tests, no network).
- Tune with environment variables in `/opt/discord-silence-bot/.env` (add them to the playbook to make them stick):
  `INVESTIGATOR_MAX_STEPS` (8 model rounds, up to 4 tool calls each), `INVESTIGATOR_DEADLINE_SECONDS` (900), `INVESTIGATOR_LLM_TIMEOUT_SECONDS` (300),
  `INVESTIGATOR_MODEL` (empty: whatever is loaded), `INVESTIGATE_AUTO_LABELS`, `INVESTIGATE_AUTO_MAX_AGE_MINUTES` (60),
  `INVESTIGATE_AUTO_REPEAT_HOURS` (12).
- Rotate the Graylog token: delete `/opt/discord-silence-bot/graylog-token` and re-run the play (it also replaces a token
  that stops working). OpenSearch password: delete `opensearch-password` and re-run.

## Not verified yet

1. **`page=true` in a real page's silence link** (proof step 3). Custom labels are confirmed to appear (`severity`, `stack`).
   After the next real page, `docker logs discord-silence-bot | grep "(auto)"` shows whether the automatic run started. If
   it does not, read labels from Grafana's alert API instead.
2. **Whether Graylog honours `token_ttl: P3650D`.**

Resolved: Graylog's search API works on 7.1; the loaded model calls tools (4 calls on a test alert, 21 on a real one);
time per investigation is 1 to 7 minutes; a vulnerability alert is about 3 minutes.

## Not built (possible next steps)

- Investigating from Telegram (it has no reactions the bot reads; a `/investigate` command would need Telegram polling).
- Container logs straight from a host (`docker logs` over SSH): deliberately left out, since it needs a credential that can
  run commands. Logs the hosts already ship to Graylog are covered.
- A memory of past investigations (e.g. "this fired three times this week, each time noise").
