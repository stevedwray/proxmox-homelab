# Sprint 05: management-stack decommission

Decommission the legacy management-stack LXC at `192.168.1.70`, which currently runs
Portainer CE, Nginx Proxy Manager, a central Docker registry, and Trivy.

**Detail level:** Sketch — flesh out before starting this sprint.

**Dependency:** This sprint cannot start until sprints 01, 02, and 03 are complete
(all Portainer-managed endpoints re-homed to infra Portainer).

---

## Current state

**Live stack:** `management-stack` at `192.168.1.70`, VMID 101

| Container | Replacement |
|---|---|
| portainer | infra Portainer in `mgmt_seg` |
| portainer-agent | still needed during transition |
| nginx-proxy-manager | Traefik (already running in `edge_seg`) |
| central-registry | Harbor (already running in `infra_seg`) |
| registry-ui | Harbor UI |
| trivy-scanner | Harbor built-in Trivy |

---

## Pre-conditions

- [ ] All Portainer endpoints (gaming, media, torrent) re-registered to infra Portainer
- [ ] All NPM proxy routes inventoried and migrated to Traefik labels
- [ ] NPM LE certificates for `*.gibbsgreatly.xyz` (non-lab domain) handled
  - step-ca / Traefik handle `*.lab.gibbsgreatly.xyz` only
  - Non-lab certs may require separate consideration (Cloudflare DNS challenge, etc.)
- [ ] `central-registry` image blobs evaluated — any non-reproducible images migrated to Harbor
- [ ] No active services depend on `192.168.1.70` for routing or registry access

---

## Key considerations

- **NPM route inventory**: NPM admin at `http://192.168.1.70:81` is only accessible
  from within the management LXC network. Options for access:
  - Use `pct exec 101 -- curl http://localhost:81/api/...` (read-only NPM API)
  - Or: temporarily expose port 81 inbound for inventory
  - This is the primary blocker — must be done before decommission
- **Non-lab TLS certificates**: NPM holds LE certs for the non-lab domain
  (`gibbsgreatly.xyz`). These must be accounted for before NPM is removed.
  Traefik with ACME DNS challenge (Cloudflare) is the likely replacement.
- **central-registry data**: the `harbor_registry_data` named Docker volume may contain
  image layers not yet in Harbor. Audit before destroying.
- **Portainer migration is gradual**: infra Portainer can have all endpoints added
  while management-stack Portainer is still running. The old Portainer is only
  removed after all endpoints are confirmed live in the new one.

---

## Steps (to be detailed)

1. Inventory NPM routes (requires access to NPM admin)
2. For each NPM route: create equivalent Traefik rule in the target service's compose
3. Handle non-lab TLS certificates
4. Audit `central-registry` image blobs, migrate any needed to Harbor
5. Confirm all Portainer endpoints are in infra Portainer and healthy
6. Stop management-stack containers one by one, verify nothing breaks
7. Snapshot LXC before destruction
8. Destroy management-stack LXC (VMID 101)
9. Remove `192.168.1.70` from any DNS, routing, or config references
