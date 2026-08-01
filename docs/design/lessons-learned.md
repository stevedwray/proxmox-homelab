# Lessons Learned

Distilled observations from development passes — things that are non-obvious, caused
problems, or must be remembered for future rebuilds. The raw session notes are in
`docs/design/archive/Observations.md`.

## Infrastructure and networking

**Portainer agent and server versions must match exactly.**
Agent v2.40.0 uses TLS from the first byte; older servers send a plain-HTTP handshake and
the connection fails. A mismatched agent also locks to the first server that claims it — a
restart is required to clear the pairing state. Pin agent and server to the same explicit
version tag in all compose files. Never use `latest`.

**IP allocation must be verified with a ping, not just IPAM.**
NetBox records intended allocations but cannot detect addresses live on the network that
were never registered. Before assigning any IP: `ping -c 3 <ip>` from the same subnet.
If it responds, the address is in use regardless of what IPAM shows.

**Default Terraform workspace targets `pve`, not `pve-test`.**
Without `TF_WORKSPACE=pve-test` (set by `.env`), `terragrunt apply` targets the production
node. Any operation that mutates running containers on `pve` without intent is the result
of a missing workspace export. The `with-secrets` wrapper handles this when `.env` is
correctly configured.

**SDN zone type is VLAN, not Simple.**
The original plan used Simple zones (Proxmox holds gateway IPs, performs SNAT). The settled
design uses VLAN zones with MikroTik as the L3 gateway. `snat: false` on all SDN zones is
mandatory — SNAT at Proxmox double-NATs with MikroTik and breaks LAN-to-container ingress.
The Terraform SDN provisioner handles Simple zones only; VLAN zones are applied by
`ansible/00-initial-setup/proxmox-sdn-setup.yml`.

**`jq` should be installed in the pve-test bootstrap.**
Multiple setup and validation steps use it for Harbor and NetBox API checks. Add it to the
Ansible bootstrap alongside other base tooling.

**Contained zones (`ai_seg`, `pentest_seg`) have no direct route to `infra_seg`.**
Docker image pulls using the raw `LAB_IP_HARBOR` address time out from these zones —
confirmed live via a `docker pull` that hung until killed. Use `harbor.${LAB_DOMAIN}`
(routed through Traefik/`edge_seg`) instead, matching `deploy-pentagi-stack.yml`'s
`pentagi_framework_host`-style pattern. This reuses whatever `<zone>→edge_seg:443` rule
the stack likely already needs for other reasons (OIDC, LM Studio), so it's usually not
an extra firewall rule.

**Live MikroTik state can silently diverge from `network/*.yaml` documentation.**
A rule documented as an FQDN-based allowlist "the MikroTik must enforce via
address-lists" turned out, on live inspection via the router's own read-only REST API
(`MIKROTIK_READONLY_USER`/`MIKROTIK_READONLY_PASSWORD`), to be a flat subnet-wide accept
rule with zero address-lists configured — the FQDN allowlist was the original intent,
never the actual enforcement. Read the router's live state via the read-only API before
extending a zone's firewall policy; don't assume the `.yaml` docs are ground truth.

**`ansible.builtin.fetch` is a poor choice for large files.**
It uses the `slurp` module internally — base64-encodes the entire remote file and ships
it through Ansible's JSON result channel, with no streaming. An ~845MB real-world
tarball took 18+ minutes and never completed. `ansible.posix.synchronize` (an rsync
wrapper) does an efficient binary/delta transfer instead; the same transfer dropped to
under 3 minutes. Reserve `fetch`/`copy` for genuinely small files.

**Shared roles with relative-path assumptions break when reused from a different
playbook location.** `lxc_base`'s CA-install task builds its source path as
`{{ playbook_dir }}/../../../../certs/homelab-root.<env>.crt` — correct only for
playbooks 4 directories deep under `terraform/lxc/ansible/playbooks/`. Reusing the role
from a playbook at a different depth (e.g. `ansible/00-initial-setup/`, 2 deep) silently
resolves the path outside the repo and skips CA install with no error — no failure, just
quietly wrong. Don't reuse a shared role outside the directory depth it was written for;
write correctly-pathed one-off tasks instead if the role can't be generalized.

## Harbor

**Harbor's own images pull from Docker Hub on the first deployment pass.**
This is expected and documented. Harbor cannot source its own images from itself before it
exists. On subsequent passes, all images come from Harbor. This is the Stage 1 → Stage 2
transition in the bootstrap model.

**Harbor scan results lag after a proxy-cache pull and may need an explicit trigger.**
After a `docker pull` through the proxy cache, `scan_overview` can remain `null` for some
time. Trigger the scan endpoint explicitly and poll the artifact list until the Trivy
summary appears. Repository paths for nested image names (e.g., `goauthentik/server`) need
double URL-encoding in API calls.

**Harbor GC schedule API requires a 6-field cron string (seconds as first field).**
The standard 5-field cron `0 3 * * 0` is rejected. Use `0 0 3 * * 0` instead.

## Secrets and configuration

**step-ca ACME challenge type must be httpChallenge, not tlsChallenge.**
step-ca verifies domain ownership by calling back to Traefik on port 80. Using tlsChallenge
requires step-ca to reach Traefik on port 443 with a valid cert — a circular dependency
during initial PKI bootstrapping. Requires MikroTik policy: `mgmt_seg → edge_seg tcp/80`.

**LE staging CA for all pve-test dev passes.**
Always use `https://acme-staging-v02.api.letsencrypt.org/directory` in Traefik's
`letsencrypt` resolver for pve-test development. Staging certs show
`(STAGING) Let's Encrypt` in browsers — this is correct and expected. Switching to
production consumes rate-limit quota and is only done when promoting to `pve`.

**LE acme.json must be persisted outside the LXC.**
The ACME cert storage lives inside the LXC filesystem. Rebuilding the LXC destroys the
cert, triggering a new LE request. On pve-test with the staging CA this is harmless; on
production it consumes rate-limit quota. The fix is platform-supported `extra_mount_*`
fields in `stack.yaml` so `/opt/proxy-stack/certs` is persisted.

## Authentik

**Authentik must be in `mgmt_seg` with explicit allow rules from `edge_seg` and any app zone.**
Traefik (edge_seg) reaches the Authentik forward-auth endpoint at `192.168.20.10:9000`.
Any service that delegates auth to Authentik must also be able to reach it. Verify zone
reachability before wiring up any protected route.

**Authentik initial setup and OIDC provider configuration are currently manual.**
After deployment, an operator must use the web UI to create the initial admin user, generate
an API token, create Proxy Providers for Traefik forward-auth, and create OIDC providers for
each integrated service (Grafana). This is the main obstacle to a fully automated rebuild.
The `terraform-provider-authentik` can automate these steps and should be implemented before
the platform is considered rebuild-safe.

**LE staging on `pve-test-vm` breaks backend-side OIDC discovery against Authentik's
*public* route — but the fix is the internal endpoint, not "wait for pve".**
`authentik-stack/edge.yaml` uses the standard `letsencrypt` resolver (not the
`step-ca`-backed override Harbor gets), so on `pve-test-vm` its cert is Let's Encrypt
*staging* — untrusted by design (see the LE staging CA note above). Any backend service
doing a server-side OIDC discovery fetch (not a human clicking through a browser
warning) will hard-fail TLS verification against `authentik.${LAB_DOMAIN}` on
`pve-test-vm`. **This does not mean OIDC is unvalidatable pre-promotion** — a first pass
at this problem wrongly concluded that and deferred it, which was wrong and got
corrected the same session. The actual fix: point the app's discovery URL at
`authentik-int.${LAB_DOMAIN}` (step-ca-issued direct-TLS endpoint in `mgmt_seg`,
already proven for Grafana/Portainer — see
`docs/step-ca-implementation/internal-tls-consumer-matrix.md`), which needs a new
`<zone> → mgmt_seg:443` firewall rule if the app's zone is contained (`ai_seg`,
`pentest_seg`) and doesn't already reach `mgmt_seg`. Same root cause also affects the
`llm.${LAB_DOMAIN}` (LM Studio) route, which has no split-endpoint override in
OpenWebUI's case (see below) and so stays on the public route, accepted as a
browser-only click-through wart rather than fixed.

**Apps without a split authorize/token-endpoint override can't cleanly use
`authentik-int` for the *interactive* leg — check first, don't assume.** Grafana and
Portainer set `token_url`/`api_url` to the internal endpoint while keeping `auth_url`
(the browser redirect target) on the public one — that's why they work today with an
LE-staging cert nobody trusts. Generic OIDC clients that derive every endpoint from one
`server_metadata_url` (OpenWebUI's `authlib`-based provider is one; so is Harbor's,
already flagged "explicitly deferred" in the consumer matrix for this exact reason) have
no such split — pointing them at `authentik-int` sends the *browser* there too, not just
the backend. That's fine as long as the operator's own client trusts the pve-test-vm
step-ca root (`certs/homelab-root.pve-test-vm.crt`) and can reach `mgmt_seg:443`/`:9443`
directly (LAN already could, in this case, no new rule needed for that side) — but it's
a real architectural difference from the Grafana/Portainer pattern, not a drop-in
substitution. Confirm which category an app falls into before assuming its migration to
`authentik-int` is as simple as Grafana's was.

**`authlib`'s real HTTP client (`httpx`) ignores the container's system CA trust store
entirely — it loads its own bundled `certifi` file.** A bind-mount that correctly fixes
`urllib`/`aiohttp` TLS verification (`/etc/ssl/certs/ca-certificates.crt` at its usual
path) leaves `authlib`'s actual discovery/token fetches still failing, silently, with no
error surfaced anywhere except a wrong/missing redirect. Confirmed by reading the actual
traceback through `authlib → httpx_client → httpx → httpcore`, not by guessing from the
symptom. Fix: also bind-mount the trusted CA bundle onto
`/usr/local/lib/python{version}/site-packages/certifi/cacert.pem` (or wherever
`certifi.where()` reports for the image). When manually appending a cert to an existing
PEM bundle file (rather than bind-mounting), a missing newline before `-----BEGIN
CERTIFICATE-----` silently corrupts the previous entry — verify with `openssl x509 -in
<bundle> -noout -subject` after any manual edit, not just a line count.

**`scripts/provision.sh --stack <name>` never reconciles Traefik/DNS/Authentik-app
config for that stack — full runs do it automatically, single-stack runs don't.**
Every `--stack` invocation logs `"SKIP edge reconcile: single-stack mode (activate-edge
phase handles this)"`, easy to miss in a long log. `activate-edge` is a phase of the
*full teardown-cycle* tooling (`scripts/teardown-deploy-test.sh`), not something
`--stack` triggers on its own — deploying a brand-new stack with `provision.sh --stack`
alone leaves its edge route unpublished indefinitely, with no error, while the container
itself runs fine and looks correctly configured. Symptom: the public hostname keeps
behaving like nothing changed no matter what gets fixed on the app side, because
requests never reach the new container's corrected code at all. Fix for a single new
stack outside a full cycle: run `terraform/lxc/reconcile-edge.py --apply <path to that
stack's edge.yaml>` directly (scoping to one manifest also avoids tripping over
unrelated stacks with pre-existing reconcile issues — a full un-scoped run can crash
entirely on a single stale manifest elsewhere), then push the result via
`ansible-playbook deploy-proxy-stack.yml -e traefik_generated_source_dir=<generated
dir>`, replicating what `reconcile_all_edge()` in `provision.sh` does for full runs.

## SearXNG

**SearXNG's stock default engine set (`use_default_settings: true`, no
`engines:` override) is largely non-functional for a self-hosted instance
behind a residential/lab IP — this looks like a migration regression but
usually isn't.** Confirmed live 2026-08-02 on `ai-services-stack`: of the
defaults enabled for the `general` category, `duckduckgo`/`duckduckgo web`
failed with a hard TCP connect timeout to `html.duckduckgo.com`'s Azure IP
— reproduced identically from a completely separate workstation on the same
WAN uplink, proving it's a network-path issue upstream of the lab, not an
`ai_seg` (or any zone's) firewall gap. `google cse`, `startpage`, `brave`,
and `qwant` all connect fine but bot-detect and suspend/CAPTCHA scraped
requests within a query or two (`SearxEngineTooManyRequestsException`,
`Suspended: CAPTCHA`) — an inherent problem with unauthenticated scraping
from a small pool of source IPs, present on any SearXNG deployment with
this engine set, not something a migration introduces. Two engines *not*
enabled by default came back with real, relevant results and no
bot-pushback when tested directly: `mwmbl` (independent crowdsourced index)
and `searchmysite` (indexes personal/independent sites). Practical
consequence for the app consuming SearXNG: enabled-but-broken engines don't
fail fast — they eat the full per-engine timeout on every single query, so
a query that would've had a real answer from a working engine still surfaces
as "no results" upstream (OpenWebUI: `404: [ERROR: No results found from
web search]`) because the response never comes back in time. Fix: disable
the broken/blocked engines and enable ones actually confirmed reachable, via
an `engines:` block appended to `settings.yml` — reachability is
network/reputation-dependent, so re-verify with a direct
`/search?q=X&format=json&engines=<name>` call against the live instance
before trusting any specific engine list, rather than assuming SearXNG's
shipped defaults work out of the box.

## Chainloop

**Chainloop has no Docker Compose self-hosting path.**
Chainloop self-hosting requires Helm on Kubernetes. A compose extraction from `helm template`
is unsupported and unpatchable. Use the Chainloop Cloud free tier for Phase 05 acceptance
criteria, or defer until a Kubernetes layer exists in the lab.
