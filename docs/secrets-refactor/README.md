# secrets-refactor

Move secret **values** out of Git-tracked SOPS files and into OpenBao, so
that a branch checkout, merge or rebase can never again silently restore an
old password.

- **Design:** [secrets-design.md](secrets-design.md). It holds the decisions
  and their reasoning.
- **Plan:** [plan.md](plan.md). It holds the step blocks for the local model,
  plus the operator-only blocks.
- **Patches:** [patches/](patches/). There are 16 pre-built, pre-verified
  patches, one per step.

## Status

**2026-09-28: design and plan complete. No step has been executed.**
Nothing live has changed.

All 16 patches were generated and applied cleanly, in order, on top of
`d41be395`. Python tools pass their unit tests, playbooks pass
`--syntax-check` and `ansible-lint`, and shell passes `shellcheck`. SOPS
retirement (plan block F) is deliberately not pre-generated. It is written
against the branch as it is after the recovery test.

## Decisions (operator, 2026-09-28)

| Topic | Decision |
| --- | --- |
| Deploy-time auth (`with-secrets`, agents) | Read-only AppRole per environment, workstation-held; no Authentik dependency |
| Human auth | Authentik OIDC, for the UI and writes only; break-glass via the recovery key and `generate-root` |
| USB seal key | Stays inserted in `pve`; unattended unseal; host bind mount, so `vzdump` never includes it |
| Bootstrap kit | Two copies: a Bitwarden secure note, and a passphrase `kit.age` on USB B. Not age-key encrypted |
| Cutover | Reconcile against live, bulk import, parity check, freeze SOPS, flip the default |
| CI | GitHub OIDC → OpenBao `jwt-github` |
| KV layout | KV v2; one entry per service/host; field names = env var names; `max_versions` 20 |
| Snapshots | After each helper write, plus nightly; to `nas.gibbsgreatly.xyz` through pve's existing NFS mount (`/mnt/nas-backup`) |
| Retention | 90d post-write / 14 daily / 8 weekly / 12 monthly; never fewer than the newest 7 |
| UI route | Through Traefik (EdgeManifest + edge reconciler); Traefik trusts the homelab CA for HTTPS backends |
| Install | Native pinned `.deb` + systemd (like step-ca); no Docker or Harbor dependency |
| OpenBao config | Ansible playbook against the API, with an explicit admin token; SecretIDs made by hand |
| Alerting | Metric + Grafana panel now; real alerting is a separate project (monitoring has none today) |

## Findings along the way (not part of this plan)

- **`netbox-populate` has failed every night since at least 2026-09-23**:
  `sudo apt-get install sops` needs a password on the self-hosted runner.
  Step 15 removes the SOPS dependency. Even when that step worked, the job
  loaded only `secrets.pve.enc.yaml`, not the common file its script also
  needs (`NETBOX_API_TOKEN`, `MIKROTIK_*`). The new `ci-netbox-populate`
  profile includes them.
- **`preflight-production-mikrotik.sh`** also loaded only the pve SOPS
  file, although its `MIKROTIK_*` checks need common values. Step 14 routes
  it through `./with-secrets-prod`.
- **`prod/pve-infra`** (protected, last commit 2026-05-25) carries a stale
  pre-split `secrets.pve.enc.yaml`. It is excluded from reconciliation.
- **Keys with no consumer in the repo** are imported, not dropped, into
  `kv/services/legacy-unused`: `NPM_DB_PASSWORD`, `OMADA_*` (4) and
  `TF_VAR_dayz_steam_*` (2). `GOOGLE_CSE_*` and `CURSEFORGE_API_KEY` also
  have no code consumer but were placed with their likely owners. These are
  candidates for deletion after the cutover.
- **`pve-framework`** is still in `PRODUCTION_NODES` and still has a secrets
  file, although the Framework is no longer a Proxmox node. The plan
  preserves it as-is (`hosts/pve-framework`, `deploy-pve-framework`).
  Removing it is a separate decision.

## Hand-back log

Each executed step appends an entry here: the step id, the date, what
changed, and every gate's actual result. See
`.github/prompts/implement-step.prompt.md`.

_(none yet)_
