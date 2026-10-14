# Wazuh tuning runbook

Read-only survey tooling used for the 2026-10-15 baseline. Phase 0 of plan.md replaces
these three scripts with one helper and a playbook (`gvm_tuning.py` is the model).

## Where things are

| Piece | Address |
|---|---|
| wazuh-stack LXC | 192.168.40.15 (vmid 40015, `infra_seg`), containers `wazuh-stack-manager`, `wazuh-stack-indexer`, `wazuh-stack-dashboard` |
| Indexer API | 127.0.0.1:9200 on the host (HTTPS, user `admin`, secret `WAZUH_INDEXER_ADMIN_PASSWORD`) |
| Manager API | 127.0.0.1:55000 on the host (HTTPS, user `wazuh-wui`, secret `WAZUH_API_PASSWORD`) |
| Manager config | `ossec.conf` staged from the playbook into the `wazuh_etc` volume; rules in `/var/ossec/etc/rules/local_rules.xml` (volume, currently the stock 19 lines); agent groups in `/var/ossec/etc/shared/<segment>/` |
| Survey scripts | `terraform/lxc/ansible/files/wazuh-tuning/survey_alerts.py`, `survey_agents.py`, `survey_noise.py` |

## Running a survey (read-only)

The scripts expect the APIs on the local machine, reached through an SSH tunnel, and
read the secrets from the environment, so they run under the production wrapper:

```bash
export TASK_APPROVAL=wazuh-tuning-survey-readonly
./with-secrets-prod bash -c '
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes \
      -L 19200:127.0.0.1:9200 -L 55000:127.0.0.1:55000 \
      root@192.168.40.15 "timeout 120 tail -f /dev/null" & TP=$!
  for i in 1 2 3 4 5 6 7 8; do (echo > /dev/tcp/127.0.0.1/19200) 2>/dev/null && break; timeout 1 tail -f /dev/null; done
  python3 terraform/lxc/ansible/files/wazuh-tuning/survey_alerts.py
  kill $TP'
```

`survey_alerts.py` and `survey_noise.py` use the indexer (port 19200); `survey_agents.py`
uses both. All three only issue GET requests and search queries. `survey_noise.py` has the
rule ids it breaks down (87907, 550, 2501, 510, 5710) at the top of its body: change them
to look at another rule.

## Gotchas learned

- The wrapper treats `bash -c` as mutating, so a named `TASK_APPROVAL` is required even
  for these read-only runs.
- A shell command that nests several levels of quoting around the Python or jq can trip
  Claude Code's safety classifier; keep scripts in files, as above.
- `track_total_hits` defaults to 10,000: use it explicitly (the scripts do) or totals
  look capped at exactly 10,000.
- `full_log` is a text field, not aggregatable; aggregate on `rule.*`, `agent.name`,
  `syscheck.path`, `data.*` fields.
- The dashboard container being `unhealthy` is the healthcheck's 401, not an outage.
- `local_rules.xml` and shared agent config live in the `wazuh_etc` named volume, not on
  the host filesystem: the playbook must deliver them (like the authd password file via
  `docker cp`) and validate with `wazuh-analysisd -t` before reloading.
- Docker health checks are logged by the agents' `docker-listener` wodle as rule 87907
  events; that is the single biggest noise source.
