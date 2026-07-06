# Production Stack Reboot Audit (via Graylog)

## Purpose

First real-world use of the newly-deployed production Graylog rollout
(see [graylog-migration-plan.md](./graylog-migration-plan.md)): the operator
is rebooting each managed `pve` stack in turn, and Graylog is used to watch
each stack's boot sequence for errors or latent breakage that hadn't been
noticed before centralized logging existed.

## Method

For each stack: reboot it, then query Graylog's search API
(`source:<stack>`, recent time range) and read the actual boot sequence —
not just severity-filtered (`level:0-3`) results. See the note under
ci-runner-01 below: real failures can log at informational severity, so
filtering by level alone is not sufficient.

## Findings by stack

### ci-runner-01 (2026-07-06)

**🔴 GitHub Actions runner service down — needs re-registration.**

Boot itself was clean (Docker containers, Portainer agent, networking all
came up normally, ~1.6s systemd startup). But the GitHub Actions self-hosted
runner failed to reconnect:

```
runsvc.sh: √ Connected to GitHub
runsvc.sh: Failed to create a session. The runner registration has been deleted from the server,
           please re-configure. Runner registrations are automatically deleted for runners that
           have not connected to the service recently.
runsvc.sh: Runner listener exited with error code 1
runsvc.sh: Runner listener exit with terminated error, stop the service, no retry needed.
systemd:   actions.runner.stevedwray-proxmox-homelab.ci-runner-01.service: Deactivated successfully.
```

GitHub auto-deletes a self-hosted runner's registration if it hasn't
connected in a while. The systemd service gave up after one failed attempt
rather than retrying indefinitely.

**Impact:** the runner is currently down and will not pick up any GitHub
Actions jobs for this repo until fixed.

**Fix required (not yet done):** generate a fresh registration token from
the GitHub repo/org settings (Settings → Actions → Runners → New
self-hosted runner), then re-run the runner's `config.sh` with that token
on `ci-runner-01`, and restart the `actions.runner.*` systemd service.

**Notable methodology finding:** all of the failure messages above logged at
`level:6` (informational) — a `level:(0 1 2 3)` severity-filtered search on
`ci-runner-01` over the same window returned **zero** results. Severity
alone would have missed this entirely; the failure was only visible by
reading actual message content.

**Status:** identified, not yet fixed.

---

### step-ca-stack (2026-07-06)

**✅ Clean boot, no issues.**

Two benign warnings during systemd-networkd/docker.service startup
(`Referenced but unset environment variable... DOCKER_OPTS`, `Failed to
increase receive buffer size for general netlink socket, ignoring:
Operation not permitted`, `Unable to load sysctl monitor BPF program,
ignoring`) — all expected in an unprivileged LXC container (no
`CAP_NET_ADMIN` for those specific kernel tuning operations); explicitly
"ignoring" in the log, no functional impact.

**Methodology note:** `step-ca` runs as a **native systemd service**
(`step-ca.service`), not a Docker container — searching
`application_name:docker-*` for this source found nothing (only
`portainer-agent`, which *is* Docker), which looked like a missing-service
red flag until re-checked without that filter. The actual CA process starts
and logs cleanly:

```
systemd:  Started step-ca.service - step-ca internal certificate authority.
step-ca:  badger: All 1 tables opened in 1ms, replay took 12.143µs (no corruption)
step-ca:  Starting Smallstep CA/0.30.2 (linux/amd64)
step-ca:  Serving HTTPS on :443 ...
step-ca:  Serving HTTP on :9443 ...
```

No `level:(0 1 2 3)` messages at all for this source over the reboot window.

**Status:** verified healthy, no action needed.

---

## Query pattern used

```
source:<stack-name>
```
over a relative time range covering the reboot, sorted by timestamp,
reading `application_name` and `message` fields directly rather than
relying on `level` filtering alone.
