# Wazuh tuning runbook

Tooling (Phase 0): `files/wazuh-tuning/wazuh_tuning.py` (measurement modes),
`must_fire.py` + `must_fire_cases.json` (detection regression suite) and the playbook
`playbooks/wazuh-tuning.yml`. The helper runs on the wazuh-stack host, so no SSH tunnel
is needed.

## Where things are

| Piece | Address |
|---|---|
| wazuh-stack LXC | 192.168.40.15 (vmid 40015, `infra_seg`), containers `wazuh-stack-manager`, `wazuh-stack-indexer`, `wazuh-stack-dashboard` |
| Indexer API | 127.0.0.1:9200 on the host (HTTPS, user `admin`, secret `WAZUH_INDEXER_ADMIN_PASSWORD`) |
| Manager API | 127.0.0.1:55000 on the host (HTTPS, user `wazuh-wui`, secret `WAZUH_API_PASSWORD`) |
| Manager config | `ossec.conf` staged from the playbook into the `wazuh_etc` volume; rules in `/var/ossec/etc/rules/local_rules.xml` (volume, currently the stock 19 lines); agent groups in `/var/ossec/etc/shared/<segment>/` |
| Tooling | `terraform/lxc/ansible/files/wazuh-tuning/` (helper, suite, unit tests), `playbooks/wazuh-tuning.yml` |

## Running it (read-only)

Work from a worktree of the branch you want shipped. The wrapper needs a named
`TASK_APPROVAL` even for read-only runs (ansible-playbook counts as mutating).

```bash
export TASK_APPROVAL=wazuh-tuning-phase0-baseline ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles
INV=~/git/proxmox-homelab/terraform/lxc/environments/pve/wazuh-stack/inventory.yml
T() { ./with-secrets-prod ansible-playbook -i $INV -u root \
      terraform/lxc/ansible/playbooks/wazuh-tuning.yml </dev/null "$@"; }

T -e tune_mode=health -e tune_tag=baseline     # containers, heap, queues, versions
T -e tune_mode=alerts -e tune_tag=baseline     # 24 h by rule/agent/level/group
T -e tune_mode=noise  -e tune_args=87907 -e tune_tag=baseline
T -e tune_mode=mustfire                        # detection regression suite (logtest only)
T -e tune_mode=sample_start                    # 30 s sampler; sample_log / sample_stop
```

JSON results land in `docs/wazuh-tuning/artifacts/<tag>-<mode>.json` (ignored); compare two
with `wazuh_tuning.diff_json`. `stop_conditions()` encodes the plan's stop list.
The must-fire suite only uses logtest (no alerts written); live actions on a test agent
(apt-cacher-stack) are a separate, separately approved tier.

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
