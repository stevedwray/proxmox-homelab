# Phase 03d — Secrets Delivery Hardening

## Status

**Stage 0 workstation task — complete before first deployment. No deployed service or
completed deployment phase is required. Can be done at any time on any machine where
the age private key is available.**

## Goal

Eliminate the `.env` file from the operator workflow entirely. Replace `sync-secrets.sh` +
`source .env` with `sops exec-env`, which decrypts `terraform/secrets.enc.yaml` and injects
secrets directly into the subprocess environment without writing anything to disk.

This phase is a repository-only change. No Proxmox services are deployed or modified.

## Why now

Phase 04 introduces several new secrets (Authentik keys, Cloudflare DNS token, step-ca
passwords, Grafana credentials). Carrying the `.env` approach forward into Phase 04 would
mean spreading it further: more placeholder lines in `.env.template`, more `source .env`
references in task docs, more manual deletion obligations. Fixing the delivery model before
Phase 04 starts is cheaper than retrofitting it after.

The specific risks this phase addresses, from the threat model in `docs/design/architecture.md`:

- **TM-02 (High):** `.env` file deletion post-session is a manual step that is unreliable.
  The SEC-03 constraint ("ephemeral `.env`") depends on operator discipline, not a technical
  control. `sops exec-env` eliminates the file entirely.

- **TM-03 (High):** `bw unlock` session token scope and lifetime are undocumented. Daily use
  of `sync-secrets.sh` keeps a live Bitwarden session open. After this phase, Bitwarden is
  only needed to recover the age key — not as part of routine operations.

## What changes

| Item | Before | After |
|---|---|---|
| Operator secret delivery | `./sync-secrets.sh` → `source .env` | `./with-secrets <command>` |
| Source of truth for secrets | Bitwarden (pulled via `bw CLI`) | `terraform/secrets.enc.yaml` (SOPS-encrypted in Git) |
| Secrets on disk | `.env` file (plaintext, must be deleted) | Never written |
| `sync-secrets.sh` | Used every session | Removed |
| `populate-bitwarden.sh` | Used to sync back to Bitwarden | Removed (SOPS is canonical) |
| `.env.template` | Template populated from Bitwarden | Removed |
| Bitwarden role | Daily operational store | Recovery backup for the age private key only |

## What does not change

- `terraform/secrets.enc.yaml` is already the encrypted store — it stays as-is except for
  gap-filling and any naming alignment identified in Task 01.
- The age private key at `~/.config/sops/age/keys.txt` stays on disk. This is intentional
  and irreducible until Phase 07 (OpenBao). It is backed up in Bitwarden as
  `"proxmox-homelab age private key"`.
- CI is unaffected. GitHub Actions secrets (`SOPS_AGE_KEY`, `HARBOR_ROBOT_PASSWORD`, etc.)
  are not changed. The `sops-decrypt-check` job continues to verify decryption on push.
- Docker Compose environment variable exposure (`docker inspect`) is unchanged — this is an
  accepted limitation documented in ADR-06 until OpenBao (Phase 07).

## Bootstrap stage context

Phase 03d is Stage 0 in the three-stage bootstrap model. Stage 0 is a workstation-only
concern: it has no dependency on any Proxmox service, no dependency on any container being
deployed, and no dependency on any prior phase in the execution plan. It should be
completed once, merged into the active branch, and from that point the `.env` delivery
approach no longer exists anywhere in the repository. All subsequent stages — Stage 1 and
Stage 2 temporary and permanent container deployments (Phase 00c), and all Phase 04+
deployments — use `./with-secrets` as the sole secret delivery mechanism.

For the full three-stage model including entry and exit conditions, security control
progression, and the relationship between Phase 03d and Phase 00c, see
[docs/design/bootstrap-stages.md](../design/bootstrap-stages.md).

## How `sops exec-env` works

```bash
# Current operator workflow (to be eliminated)
export BW_SESSION=$(bw unlock --raw)
./sync-secrets.sh       # writes .env to disk
source .env             # reads .env into shell
tofu apply              # picks up TF_VAR_* from shell environment
rm .env                 # manual step — frequently missed

# New operator workflow
./with-secrets tofu apply
# Secrets are decrypted in-memory and injected into the 'tofu' subprocess only.
# When 'tofu apply' exits, the decrypted values are gone.
```

`sops exec-env terraform/secrets.enc.yaml -- <command>` decrypts the YAML file and injects
each top-level key as an environment variable into the named command's subprocess. The parent
shell environment is not modified. Nothing is written to disk.

The `with-secrets` wrapper (created in Task 03) adds automatic `SOPS_AGE_KEY_FILE` wiring so
the operator does not need to set it manually.

## Naming constraint

Terraform reads secrets from environment variables named `TF_VAR_<variable_name>`. For
example, `var.pm_api_token_secret` is set by `TF_VAR_pm_api_token_secret=<value>`.

The keys currently stored in `secrets.enc.yaml` and `sync-secrets.sh` may use a different
naming convention (e.g. `PROXMOX_TOKEN_SECRET` instead of `TF_VAR_pm_api_token_secret`).

Task 01 produces the definitive mapping. Task 02 aligns the SOPS file if needed.

## Tasks

| Task | Document | Dependency |
|---|---|---|
| 03d-01 | [Audit — decrypt and map all consumers](tasks/03d-secrets-01-audit.md) | none |
| 03d-02 | [Align SOPS file — fill gaps, fix naming](tasks/03d-secrets-02-align-sops.md) | 03d-01 complete |
| 03d-03 | [Create `with-secrets` wrapper and test all consumers](tasks/03d-secrets-03-wrapper-and-test.md) | 03d-02 complete |
| 03d-04 | [Remove old files and update all documentation](tasks/03d-secrets-04-remove-and-update.md) | 03d-03 complete and signed off |

**Important:** Do not proceed to Task 04 until Task 03 has been confirmed working for every
consumer. The old `.env` approach should remain intact until Task 04 begins.

## Prerequisites

- `sops` CLI installed and working: `sops --version`
- Age private key present at `~/.config/sops/age/keys.txt` (retrieve from Bitwarden:
  `"proxmox-homelab age private key"` — one-time retrieval; no Bitwarden session is
  required after this)
- `terraform/secrets.enc.yaml` successfully decrypts:
  `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml`
- No deployed Proxmox service is required. No prior phase must be complete.

## Acceptance criteria

- [ ] `with-secrets` script exists at repo root, is executable, and passes shellcheck
- [ ] `./with-secrets tofu plan` completes without credential errors in at least one stack
- [ ] `./with-secrets ansible-playbook ...` can authenticate to pve-test without `.env` sourced
- [ ] `./with-secrets sonar-scanner` can authenticate (SONAR_TOKEN injected correctly)
- [ ] `sync-secrets.sh` removed from repo root
- [ ] `populate-bitwarden.sh` removed from repo root
- [ ] `.env.template` removed (if it exists)
- [ ] `.env.pve-test` removed (if it exists) — or confirmed already gitignored and absent
- [ ] `scripts/setup-dev-env.sh` no longer references `.env` or `.env.template`
- [ ] `docs/reference/secrets-management.md` reflects the new flow
- [ ] All Phase 04 task docs updated — no remaining `source .env` or `Add to .env.template` instructions
- [ ] `docs/plan/README.md` security scanning section updated
- [ ] No `.env` file present in the working directory after the phase is complete

## Task document lifecycle

All four task documents are one-time repository changes. Once merged, archive them to
`docs/plan/tasks/done/`.
