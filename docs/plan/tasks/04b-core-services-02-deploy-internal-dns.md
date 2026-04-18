# 04b-core-services-02 — Deploy internal authoritative DNS server (CoreDNS)

## Overview

Deploy CoreDNS as the authoritative server for `lab.gibbsgreatly.xyz`. This service acts as the target for MikroTik's conditional forwarding rule, enabling all SDN clients to resolve Phase 04 and Phase 06 internal service names.

## Why CoreDNS

- Single static binary (no runtime dependencies)
- Container-friendly (easily runs in LXC via systemd)
- Flexible zone file or REST API configuration
- Low resource footprint (~50 MB memory)
- Ready for future integrations (ACME, metrics export)

## Deployment target

- **LXC:** `dns-stack` (VMID 151)
- **Network:** `mgmt_seg` (VLAN 20)
- **IP:** `10.57.1.13/24`
- **Gateway:** `10.57.1.1` (MikroTik)
- **Resolver:** `10.57.1.1` (MikroTik, for upstream recursion)

## Prerequisites for this task

- Phase 04 services (Authentik, Traefik, step-ca, Monitoring) all running and assigned their fixed IPs
- Phase 04 acceptance criteria all green (services respond to HTTP/HTTPS)
- CoreDNS binary available (from Harbor image or system package)
- `.env` sourced with Proxmox API credentials
- MikroTik admin credentials available for FWD rule creation

## Zone configuration

### lab.gibbsgreatly.xyz zone file

Create `terraform/lxc/ansible/files/coredns-lab.zone`:

```
$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m

;; Phase 04 core services (mgmt_seg)
authentik       A   10.57.1.10          ; identity provider
step-ca         A   10.57.1.11          ; internal CA
monitoring      A   10.57.1.12          ; observability stack

;; Phase 04 edge services (edge_seg)
traefik         A   10.57.2.10          ; reverse proxy

;; Phase 06 application services — populated during app migration
; pihole       A   10.60.0.10          (Pi-hole, migrated in Phase 06)
; arr          A   10.60.0.20          (arr stack, migrated in Phase 06)
; jellyfin     A   10.60.0.30          (Jellyfin, migrated in Phase 06)
```

### CoreDNS configuration (systemd unit)

Create `terraform/lxc/ansible/files/coredns.conf`:

```
. {
    # Serve lab.gibbsgreatly.xyz from zone file
    file /etc/coredns/lab.zone lab.gibbsgreatly.xyz

    # Non-lab queries: forward to MikroTik (upstream resolver)
    forward . 10.57.1.1

    # Logging (optional, disable for quiet operation)
    log

    # Health check endpoint (for monitoring)
    health

    # Prometheus metrics (optional)
    prometheus 0.0.0.0:9153
}
```

Add systemd unit `terraform/lxc/ansible/files/coredns.service`:

```ini
[Unit]
Description=CoreDNS — Internal authoritative DNS server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/coredns -conf /etc/coredns/coredns.conf
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=coredns

[Install]
WantedBy=multi-user.target
```

## Deployment steps

### 1. Create LXC container (dns-stack)

Use Terraform or the standard LXC creation playbook:

```bash
# Via Terraform:
cd terraform/lxc/stacks/dns-stack
terraform apply

# Or manually (if Terraform not used):
pct create 151 storage-template:vztmpl/debian-13.1-docker-template.tar.gz \
  -hostname dns-stack \
  -net0 name=eth0,bridge=tvmgmt,tag=20,ip=10.57.1.13/24,gw=10.57.1.1 \
  -cores 1 -memory 256 -swap 128 -rootfs storage-local-lvm:8
```

Start the container:

```bash
pct start 151
```

### 2. Download and install CoreDNS

Inside the container:

```bash
# Download CoreDNS (or pull from Harbor if available)
COREDNS_VERSION=1.10.1
wget https://github.com/coredns/coredns/releases/download/v${COREDNS_VERSION}/coredns_${COREDNS_VERSION}_linux_amd64.tgz
tar xzf coredns_${COREDNS_VERSION}_linux_amd64.tgz -C /usr/local/bin/

# Verify
/usr/local/bin/coredns -version
```

### 3. Deploy zone file and configuration

Copy files from the control machine via Ansible or SCP:

```bash
# Via Ansible:
ansible-playbook -i ansible/inventory/dev.yml \
  -l dns-stack \
  ansible/playbooks/deploy-dns-stack.yml

# Or manually:
pct push 151 terraform/lxc/ansible/files/coredns-lab.zone /etc/coredns/lab.zone
pct push 151 terraform/lxc/ansible/files/coredns.conf /etc/coredns/coredns.conf
pct push 151 terraform/lxc/ansible/files/coredns.service /etc/systemd/system/coredns.service
```

### 4. Start CoreDNS service

```bash
pct exec 151 -- systemctl daemon-reload
pct exec 151 -- systemctl enable coredns
pct exec 151 -- systemctl start coredns

# Check status
pct exec 151 -- systemctl is-active coredns  # should return 'active'
```

### 5. Validate CoreDNS from the Proxmox host

```bash
# Authority test (should return IP immediately, not forwarded)
dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz
# Expected: 10.57.2.10

# Non-lab recursion test (should forward to MikroTik)
dig @10.57.1.13 +short github.com
# Expected: some IP (varies by DNS resolution)

# AXFR test (zone transfer — should list all records)
dig @10.57.1.13 AXFR lab.gibbsgreatly.xyz
```

### 6. Configure MikroTik conditional forwarding

On the MikroTik control machine:

```bash
# Via REST API (requires admin credentials):
curl -sk --user "admin:${MIKROTIK_ADMIN_PASSWORD}" \
  -X POST https://192.168.1.1/rest/ip/dns/static/add \
  -H "Content-Type: application/json" \
  -d '{
    "name": "lab.gibbsgreatly.xyz",
    "regexp": "(^|\\\\.)lab\\\\.gibbsgreatly\\\\.xyz$",
    "type": "FWD",
    "forward-to": "10.57.1.13",
    "ttl": "5m",
    "comment": "Phase-04b-dns-fwd"
  }'

# Or via CLI:
/ip dns static add \
  regexp="(^|\\.)lab\\.gibbsgreatly\\.xyz$" \
  type=FWD forward-to=10.57.1.13 \
  ttl=5m comment=Phase-04b-dns-fwd
```

### 7. Validate resolution from all SDN zones

From the Proxmox host (or from inside containers):

```bash
# From build_seg (VLAN 10) resolver
dig @10.57.0.1 +short traefik.lab.gibbsgreatly.xyz  # should be 10.57.2.10

# From mgmt_seg (VLAN 20) resolver
dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz  # should be 10.57.2.10

# From edge_seg (VLAN 30) resolver
dig @10.57.2.1 +short traefik.lab.gibbsgreatly.xyz  # should be 10.57.2.10

# From infra_seg (VLAN 40) resolver
dig @10.57.3.1 +short traefik.lab.gibbsgreatly.xyz  # should be 10.57.2.10
```

All should return `10.57.2.10`.

### 8. Verify existing Phase 04 services resolve via lab zone

```bash
# Inside Traefik container
pct exec 153 -- dig +short authentik.lab.gibbsgreatly.xyz  # should be 10.57.1.10
pct exec 153 -- dig +short step-ca.lab.gibbsgreatly.xyz    # should be 10.57.1.11

# Inside monitoring container
pct exec 154 -- dig +short traefik.lab.gibbsgreatly.xyz    # should be 10.57.2.10
```

---

## Updating zone records (for Phase 06 app onboarding)

When Phase 06 applications migrate, update the zone file:

```bash
# Add new record
echo "pihole       A   10.60.0.10" >> /etc/coredns/lab.zone

# Reload CoreDNS (zero-downtime reload)
systemctl reload coredns

# Verify
dig @10.57.1.13 +short pihole.lab.gibbsgreatly.xyz
```

---

## Acceptance criteria

- [ ] LXC `dns-stack` (VMID 151) running at `10.57.1.13`
- [ ] `systemctl is-active coredns` returns `active`
- [ ] Authority response: `dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
- [ ] Recursion works: `dig @10.57.1.13 +short github.com` → an IP
- [ ] MikroTik FWD rule exists: `ip dns static print` shows regexp entry for `lab.gibbsgreatly.xyz` with forward-to `10.57.1.13`
- [ ] All four SDN zone resolvers return lab-zone answers:
  - `dig @10.57.0.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
  - `dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
  - `dig @10.57.2.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
  - `dig @10.57.3.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
- [ ] Phase 04 services resolve via lab-zone names (no hardcoded IPs in configs)
- [ ] No OOM on pve-test host; CoreDNS memory usage < 100 MB
- [ ] Zone update procedure tested with a Phase 06 dry-run entry (e.g., add pihole record, verify, remove)

---

## Rollback procedure (if DNS failures occur)

```bash
# Stop CoreDNS
systemctl stop coredns

# Disable MikroTik forwarding rule
/ip dns static disable [find comment=Phase-04b-dns-fwd]

# Revert to static A records on MikroTik (if backup exists)
/ip dns static add name=traefik.lab.gibbsgreatly.xyz type=A address=10.57.2.10

# Verify resolution still works
dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz
```

---

## Integration with Phase 06

When Phase 06 app migration begins:

1. Pi-hole deployed to `10.60.0.10` as a pure ad-blocking resolver (not authoritative)
2. Add Pi-hole record to CoreDNS zone: `pihole A 10.60.0.10`
3. Update MikroTik to also forward `*.adblocking.local` (or custom Pi-hole zone) to `10.60.0.10` if needed
4. Keep `lab.gibbsgreatly.xyz` authority on CoreDNS; Pi-hole handles ad-blocking independently

---

## Related documentation

- [Phase 04b plan](../phase-04b-internal-dns.md)
- [SDN segment routing](../reference/sdn-segment-routing.md)
- [Phase 04 prerequisites](../phase-04-core-shared-services.md)
