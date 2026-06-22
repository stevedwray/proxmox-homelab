# Portainer Agent TLS Regression After Container Recreation

**Observed:** 2026-06-20 / 2026-06-21
**Status:** Resolved 2026-06-21. Prevention fix pending (tracked as follow-up).

---

## Symptom

After running `provision.sh --stack portainer-stack` (or `--tier platform`) from any branch
that includes commit `ebafcf6` or later against a pve portainer-stack that predates that commit,
the Portainer container is recreated. After recreation, application stack environments show as
DOWN in Portainer CE and cannot be recovered by restarting agents or restoring from a post-recreation
backup alone.

---

## Root Cause

### 1. Container recreation trigger

`deploy-portainer-stack.yml` writes a `docker-compose.yml` that includes:

```yaml
volumes:
  - /etc/ssl/certs:/etc/ssl/certs:ro
```

This volume mount was added in commit `ebafcf6` (2026-05-03) for Portainer OAuth CA trust.
Production (`pve`) portainer-stack had not been provisioned since before that commit.

When provision runs, Ansible's `copy` module detects the compose file content differs from
what was on disk, writes the new file, and `docker_compose_v2 state: present` detects the
portainer service config-hash changed → **recreates the Portainer container**.

### 2. TLS handshake failure after recreation

After recreation, Portainer CE 2.27.3 cannot complete the TLS handshake when connecting to
previously registered agent endpoints. The agent logs show:

```
2026/06/20 22:09:35 http: TLS handshake error from 192.168.20.20:43972: EOF
```

Plain `curl -sk https://<agent-ip>:9001` from the portainer-stack LXC succeeds (returns
`"Missing request signature headers"` as expected), so network connectivity is not the issue.

The failure is a pairing state mismatch: Portainer's internal signing/pairing state changes when
the container is recreated. Agents paired with the previous instance reject the new TLS session.

### 3. What does NOT fix it

- **Restarting agents** — Portainer stops polling DOWN endpoints entirely after the failure.
  No new connection attempts reach the agent even after a restart.
- **Restoring from a post-recreation backup** — the broken pairing state is baked into the
  restored DB. TLS failure persists.
- **Restoring from a pre-migration backup** (Jun 19) — predates registration of the application
  environments. Restore wipes the endpoint records entirely.
- **Forcing a Portainer snapshot via API** — returns HTTP 204 but no connection reaches the agent.
- **Forcing a PUT update on the endpoint** — returns HTTP 200 but Status remains 2 (DOWN).
- **Upgrading agent versions** — not relevant. Both `portainer/agent:2.21.1` and `portainer/agent:2.40.0`
  exhibit the same behaviour against a recreated Portainer instance. Version is not the issue.

---

## Recovery

Reset each affected agent by running `docker compose down && docker compose up -d` in the
agent's compose directory (clears the agent's pairing state), then re-register the endpoint
with infra Portainer via the `migrate-portainer-stack` playbook or directly via the API.

**Compose directory varies by stack:**
- torrent, media, gaming, analysis: `/opt/portainer-agent`
- elastic-stack: `/opt/portainer` (older layout)

**API registration for manual cases** (Portainer 2.27.3 requires multipart form, not JSON):

```bash
curl -s -X POST http://192.168.20.20:9000/api/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -F "Name=<stack-name>" \
  -F "EndpointCreationType=2" \
  -F "URL=tcp://<agent-ip>:9001" \
  -F "TLS=true" \
  -F "TLSSkipVerify=true" \
  -F "TLSSkipClientVerify=true"
```

For the four stacks with `ansible_playbook: migrate-portainer-stack` in their inventory,
running `provision.sh --stack <name>` handles the reset and re-registration atomically.

After recovery: take a fresh NAS backup via `pct exec 20020 -- systemctl start portainer-backup.service`.

---

## Prevention

Once provision has run once with the current template, the on-disk compose matches and subsequent
provisions will not recreate the container. The immediate risk is gone.

Longer-term fix: add `recreate: never` to the `portainer` service in `docker_compose_v2` and
trigger recreation explicitly via a handler (same pattern as the Promtail service). This prevents
any future compose-file change from silently recreating the container mid-session.
Tracked as a follow-up — does not block VictoriaLogs work.
