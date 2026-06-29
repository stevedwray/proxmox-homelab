# Graylog Dashboards

Dashboard definitions stored as JSON, provisioned by `deploy-graylog-stack.yml`
on each fresh deploy.

## Workflow

### Exporting a dashboard from Graylog

After building a dashboard in the Graylog UI:

```bash
# List available dashboards and their IDs
curl -s -u admin:$GRAYLOG_ROOT_PASSWORD http://192.168.20.114:9000/api/views \
  | jq '.views[] | select(.type=="DASHBOARD") | {id, title}'

# Export a specific dashboard by ID
curl -s -u admin:$GRAYLOG_ROOT_PASSWORD http://192.168.20.114:9000/api/views/<id> \
  | jq 'del(.id, ._version, .created_at)' \
  > terraform/lxc/stacks/graylog-stack/dashboards/<name>.json
```

Use `jq 'del(.id, ._version, .created_at)'` to strip fields that Graylog
generates on creation — the provisioning task imports by title and lets
Graylog assign a new ID each time.

### How Ansible provisions dashboards

`deploy-graylog-stack.yml` (guarded by `graylog_deploy_runtime`) will:

1. Find all `*.json` files in this directory.
2. For each file, check if a dashboard with the same `title` already exists
   via `GET /api/views?type=DASHBOARD`.
3. If not found, create it via `POST /api/views`.

Existing dashboards with matching titles are left unchanged. To update a
dashboard, delete it in the Graylog UI and re-run the playbook (or update the
JSON and rename the title).

## Planned dashboards

| File | Purpose |
|---|---|
| `lab-logs-overview.json` | Log volume by source over time; cross-stack message table |
| `auth-security.json` | SSH logins, failed auth, sudo events across all managed LXCs |
| `docker-containers.json` | Log volume by container, stderr error rate |
| `network-devices.json` | MikroTik and NAS log explorer; DHCP, DNS, error events |
