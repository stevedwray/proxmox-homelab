# DNS and Egress Issues — Destroy/Deploy Testing

Networking failures hit in three distinct places during the 2026-04-16 destroy/deploy
test cycle. This document captures each failure, its observed behaviour, and what needs
to be fixed so that **public DNS resolvers (e.g. `1.1.1.1`) are never required**.

---

## Issue 1 — Workstation hostname resolution inconsistency

### Observed behaviour

`pve-test.gibbsgreatly.xyz` was not consistently resolvable from the workstation shell.

- `ssh pve-test.gibbsgreatly.xyz` worked in some direct calls.
- `scp` and commands wrapped in `bash -lc` (e.g., Ansible `local_action` or scripted
  pipelines that open a login shell) failed with DNS resolution errors.

### Workaround applied

Used `192.168.1.40` (the pve-test LAN IP) for host-side Proxmox operations and avoided
`bash -lc` wrapped calls where possible.

### Root cause hypothesis

The MikroTik split-DNS configuration for `gibbsgreatly.xyz` may not be reliably serving
the local A record for `pve-test.gibbsgreatly.xyz` across all resolution paths. Login
shells and non-login shells may pick up different `/etc/resolv.conf` entries (e.g. a
systemd-resolved stub vs the LAN gateway directly), causing split behaviour.

### Required fix

1. Confirm that `pve-test.gibbsgreatly.xyz` has a local DNS entry on the MikroTik
   (`10.57.x.x` or `192.168.1.40`) in the MikroTik static DNS table.
2. Ensure the workstation's resolver is consistently `192.168.1.1` (MikroTik LAN gateway)
   and that no fallback resolver is configured.
3. Do not rely on public DNS for `gibbsgreatly.xyz` resolution — the MikroTik must answer
   these names locally (split DNS).
4. Verify with both `ssh pve-test.gibbsgreatly.xyz` and `scp` from a fresh shell before
   considering this closed.

---

## Issue 2 — ci-runner-01 cannot resolve external names via MikroTik

### Observed behaviour

With `nameserver 10.57.0.1`, the `ci-runner-01` container could not reliably resolve
external names such as `deb.debian.org`. This blocked `apt` during the runner bootstrap.

A temporary override to `nameserver 1.1.1.1` was applied to unblock the dependency
install. This is **not acceptable** as a steady state.

### Root cause hypothesis

The MikroTik `vlan10-build` interface (`10.57.0.1`) was not forwarding DNS queries to an
upstream resolver during the bootstrap window. Likely causes:

- DNS forwarding not enabled or not configured to reach the WAN upstream from the MikroTik
  at the time the container was brought up.
- The MikroTik DNS service may have been configured but the VLAN 10 interface was not yet
  allowed to use it (firewall input chain blocking UDP/TCP 53 from `10.57.0.0/24`).
- Timing: the MikroTik interface was just created and the DNS cache was cold.

### Required fix

1. Verify the MikroTik DNS service is enabled: `/ip dns print` should show `allow-remote-requests: yes`.
2. Confirm the MikroTik firewall input chain allows DNS from `build_seg` (`10.57.0.0/24`)
   to `10.57.0.1` on UDP/TCP port 53.
3. Confirm the MikroTik WAN uplink is correctly forwarding external queries (check `/ip dns
   cache` after a test lookup from a known-good host).
4. Test by executing `nslookup deb.debian.org 10.57.0.1` from a shell on `ci-runner-01`
   *before* the bootstrap playbook runs.
5. Only once the MikroTik-local resolver works end-to-end may the `1.1.1.1` temporary
   entry be considered removed — it must already be absent in the current `deploy-ci-runner.yml`.

### Persistence note

Proxmox overwrites `/etc/resolv.conf` on container boot from its internal config. A
post-provision file copy is not enough. The current `deploy-ci-runner.yml` installs
`homelab-runner-resolver.service` to restore the correct resolver before the runner starts.
Ensure that service sets `nameserver 10.57.0.1`, not a public resolver.

---

## Issue 3 — GitHub runner offline after reboot / broker TryAgain errors

### Observed behaviour

After the runner service started post-reboot, the runner logs showed repeated:

```
Socket Error: TryAgain
```

while attempting to reach the GitHub Actions broker endpoint:

```
https://pipelinesghubeus7.actions.githubusercontent.com/...
```

The runner was running locally, but GitHub still reported the runner as `offline`.
The playbook's online check was blocked by this connectivity failure, not by runner
configuration.

### Root cause hypothesis

The `homelab-runner-resolver.service` restores the resolver before the runner starts, but
if the MikroTik's DNS forwarding itself is not working at that moment (Issue 2 above),
the runner cannot resolve the GitHub broker FQDN and the socket errors follow immediately.
This is therefore a downstream symptom of Issue 2.

Additionally, the `TryAgain` code in the .NET socket layer indicates a transient DNS
failure (EAGAIN/servfail), not a hard NXDOMAIN — consistent with the MikroTik resolver
being reachable but not yet returning answers.

### Required fix

1. Fix Issue 2 first. Once `10.57.0.1` can resolve external names reliably, the broker
   FQDN (`*.actions.githubusercontent.com`) should resolve successfully and the runner
   should come online.
2. Verify that `homelab-runner-resolver.service` has `Before=actions.runner.*.service`
   (or equivalent) in its unit ordering so the resolver is fully restored before the
   runner attempts its first broker connection.
3. Confirm the MikroTik does not block HTTPS egress from `10.57.0.0/24` to the internet
   on TCP 443. The runner's broker connection is outbound HTTPS only — no inbound ports
   are needed.
4. Add a post-reboot smoke test: after the LXC reboots, SSH in and run
   `curl -s https://api.github.com` before checking runner status in GitHub.

---

## Steady-state invariants

These are non-negotiable networking requirements. Any divergence from them must be treated
as a blocking defect, not a workaround:

| Requirement | Detail |
|---|---|
| No public DNS resolvers in any container | All SDN workloads use their zone's MikroTik gateway IP as resolver |
| `build_seg` resolver | `10.57.0.1` |
| `mgmt_seg` resolver | `10.57.1.1` |
| `infra_seg` resolver | `10.57.3.1` |
| MikroTik forwards public names via DoH | Configured on the MikroTik WAN path, not bypassed |
| Split DNS for `gibbsgreatly.xyz` | `pve-test` and homelab hostnames resolve locally via MikroTik static DNS |
| No workstation fallback to public resolver | `192.168.1.1` is the sole resolver entry on the workstation |

---

## Verification sequence before next deploy cycle

Run these checks before starting a destroy/redeploy pass:

1. `nslookup pve-test.gibbsgreatly.xyz 192.168.1.1` — must return `192.168.1.40`
2. `nslookup deb.debian.org 10.57.0.1` — must return a valid IP (test from a host on `build_seg`)
3. `nslookup api.github.com 10.57.0.1` — must return a valid IP
4. `ssh pve-test.gibbsgreatly.xyz` and `scp /dev/null pve-test.gibbsgreatly.xyz:/tmp/` — both must succeed from the workstation
5. After `ci-runner-01` redeploy and LXC reboot: `curl -s https://api.github.com` from inside the container, then confirm runner online in GitHub
