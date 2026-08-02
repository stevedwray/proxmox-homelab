# Production Credentials & Access Control

This document defines how production credentials are managed and accessed in this repo.

## Overview

Production secrets are kept separate from development secrets to prevent accidental exposure and to enforce strict access controls. Production access defaults to read-only and requires explicit operator approval for any mutations.

**As of 2026-07-17 there is more than one production-trust node.** `pve`
remains the original and best-documented example throughout this file, and
everything below is still accurate for it — but the mechanism is now
generic rather than pve-specific. `terraform/PRODUCTION_NODES` declares
which nodes are production (currently `pve`, `pve-framework`); each has its
own `.env.<node>` and `terraform/secrets.<node>.enc.yaml`, and its own thin
`with-secrets-prod*` wrapper (`with-secrets-prod` for `pve`,
`with-secrets-prod-framework` for `pve-framework`) over the shared engine in
`scripts/with-secrets-prod-lib.sh`. See
`docs/framework-integration/decisions.md` Decision 6 for the full rationale
and what changed. Read `pve` below as "the pattern, illustrated with the
original node" rather than as the only node it applies to.

## Current Status

As of May 22, 2026, the production Proxmox API token path has been validated
successfully:

- `terraform/secrets.pve.enc.yaml` is the active operator-managed production
  SOPS file
- the production token authenticated successfully to
  `https://pve.gibbsgreatly.xyz:8006/api2/json/version`
- the validation was read-only and returned HTTP 200

What is still incomplete:

- a committed `.env.pve` pattern has not been finalized yet
- local non-secret production targeting may still require explicit overrides
  until Task 02 is completed

## Secret Storage

### Development Secrets
- **File:** `terraform/secrets.common.enc.yaml`
- **Wrapper:** `./with-secrets`
- **Environment:** pve-test (default, safe)
- **Access:** Available to normal development workflows without restriction

### Production Secrets
- **File:** `terraform/secrets.pve.enc.yaml` (separate from dev)
- **Wrapper:** `./with-secrets-prod` (explicit production wrapper)
- **Environment:** pve (production)
- **Access:** Restricted to intentional production workflows only

This file is operator-managed local state. It should remain SOPS-encrypted and
must not be committed accidentally as plaintext.

Both files are encrypted with SOPS using age keys. See `terraform/README.md` for decryption setup.

## Environment Files

Non-secret configuration is stored in environment files (not encrypted):

- `.env` — common non-secret config for dev (gitignored)
- `.env.pve-test` — pve-test specific non-secret config (gitignored)
- `.env.pve` — production specific non-secret config (gitignored)

These contain hostnames, node names, IPs, usernames, and workspace settings—never secrets.

## Access Wrappers

### `./with-secrets` (Development, Safe Default)

Used for normal pve-test development work.

```bash
# Load dev secrets from terraform/secrets.common.enc.yaml
# Target pve-test by default
# Fail if attempting to target pve without ALLOW_PVE=true

./with-secrets terragrunt plan
./with-secrets terraform apply
```

**Safety rails:**
- Defaults to `PVE_ENV=pve-test`
- Refuses any `pve` work unless `ALLOW_PVE=true` is explicitly set
- Can only reach dev secrets in `terraform/secrets.common.enc.yaml`

**When to use:**
- All normal infrastructure work
- Stack development and testing on pve-test
- Planning and validation before any production work

### `./with-secrets-prod` (Production, Strict Controls)

Used for intentional production-only workflows.

```bash
# Load ONLY production secrets from terraform/secrets.pve.enc.yaml
# Enforce pve environment targeting
# Allow only a narrow read-only command set without approval
# Block mutating or ambiguous commands unless explicit operator approval is acknowledged

./with-secrets-prod pct list              # read-only, allowed
./with-secrets-prod terraform plan        # read-only, allowed
./with-secrets-prod terragrunt apply      # mutating, blocked without approval
```

**Safety rails:**
- Loads production secrets only (cannot accidentally load dev secrets)
- Enforces `PVE_ENV=pve` and `TF_VAR_proxmox_node=pve`
- Uses a conservative read-only command classifier
- Allows only explicitly recognized read-only commands without approval
- Blocks mutating commands unless `TASK_APPROVAL` is set

**When to use:**
- Read-only inspection of production state
- Production planning (`terraform plan`, validation scripts)
- Approved production mutations (with explicit `TASK_APPROVAL` set by operator)

## Command Classification

### Read-Only (Allowed by default through `with-secrets-prod`)

**Inventory & status:**
- `pct list`, `qm list`, `pvesm status`
- `pvesh get /api2/json/*` (read API calls)

**Validation & planning:**
- `terragrunt plan`, `terraform plan`
- `terraform validate`
- `terragrunt validate`, `terragrunt show`, `terragrunt output`
- `terraform version`
- `ansible-inventory`

**Monitoring & inspection:**
- `dig`, `ping`

Ambiguous tools such as `ssh`, `scp`, `curl`, `ansible-playbook`, and custom
scripts are treated as mutating unless explicitly approved. This is
intentional: the wrapper uses a conservative allowlist rather than trying to
infer whether an arbitrary command is safe.

### Mutating (Blocked unless explicit operator approval)

**Infrastructure mutation:**
- `terragrunt apply`, `terraform apply`
- `pct create`, `pct destroy`, `pct set`
- `qm create`, `qm destroy`, `qm set`
- SDN/firewall/storage changes

**Service deployment:**
- `ansible-playbook` with state-changing tasks
- Container start/stop/restart on production
- Service migrations or cutover operations

## Approval Workflow

### For Read-Only Operations

Read-only production commands can run through `with-secrets-prod` without approval:

```bash
# No approval needed for read-only
./with-secrets-prod terraform plan

# Produces output, no blocking
```

### For Mutating Operations

Mutating production commands require explicit per-task operator approval:

**Step 1: Preflight Summary**
Before running any mutating command, the session displays:
- target environment (production `pve`)
- operation type (mutating)
- exact objects to be changed
- specific commands that will run
- what is explicitly out-of-scope

**Step 2: Operator Approval in Chat**
The operator reviews the summary and explicitly confirms:
```
Operator: "Proceed with [task description]"
```

**Step 3: Acknowledge Approval & Execute**
After approving in chat, the operator sets the environment variable and re-runs
the command:
```bash
export TASK_APPROVAL="01-credential-controls"
./with-secrets-prod terragrunt apply
```

The wrapper cannot verify the chat transcript on its own. `TASK_APPROVAL` is
the local acknowledgement that the chat approval already happened.

**Step 4: After-Action Summary**
After the command completes, the session reports:
- what was actually changed
- success/failure status
- confirmation of expected state
- any follow-up actions needed

### Key Principles

- **No standing approval:** Each distinct mutating task requires new approval
- **No approval packets:** Approval is recorded in the chat session, not in files
- **Task-scoped:** Approval for one task does not auto-apply to different tasks
- **Explicit command:** The operator must use clear language like "proceed" or "yes"
- **Per-session:** Approval does not carry over to new Copilot sessions
- **Conservative classifier:** If a command is ambiguous, the wrapper treats it
  as mutating and requires approval

## Environment Variables

### Development Workflow
```bash
# Use with ./with-secrets
PVE_ENV=pve-test                    # default
TF_VAR_proxmox_node=pve-test        # default
ALLOW_PVE=false                     # default (blocks accidental pve work)
```

To intentionally work on pve from dev path (not recommended):
```bash
ALLOW_PVE=true ./with-secrets <command>
```

### Production Workflow
```bash
# Use with ./with-secrets-prod
PVE_ENV=pve                         # enforced
TF_VAR_proxmox_node=pve             # enforced
TASK_APPROVAL=<task-name>           # required for mutating commands
```

## Before & After Session Summaries

Every production-touching session must provide operator visibility.

### Preflight Summary (Before)
Report to the operator before accessing production:
- **Environment:** target host and pve environment
- **Access mode:** read-only vs mutating
- **Scope:** exact objects expected to be inspected or changed
- **Commands:** command class or specific commands expected to run
- **Out of scope:** what will NOT be touched

Example:
```
PREFLIGHT SUMMARY
Environment: pve (production)
Access Mode: mutating
Target: terraform/lxc/stacks/monitoring-stack/
Scope: Deploy monitoring stack infrastructure
Commands: terragrunt apply
Out of Scope: Storage configuration, network changes, other stacks
Awaiting operator approval...
```

### After-Action Summary (After)
Report results to the operator after any production access:
- **What changed:** objects inspected or modified
- **Status:** succeeded, failed, or partially completed
- **Expectations:** did the result match what was planned?
- **Follow-up:** any additional actions needed

Example:
```
AFTER-ACTION SUMMARY
What Changed: monitoring-stack LXCs created (prometheus, grafana)
Status: Apply succeeded (2 resources created)
Expectations: ✓ Matched plan
Follow-up: Stack is deployed but not yet integrated with proxy-stack
```

## Separation Rationale

### Why separate files?

1. **Accident prevention:** Using `./with-secrets` cannot load production secrets, even with `ALLOW_PVE=true`
2. **Clear intent:** Reaching `./with-secrets-prod` is an explicit choice to work with production
3. **Risk reduction:** Operators cannot casually flip a flag and suddenly load real production credentials into dev workflows
4. **Audit clarity:** Separate files make it obvious when production work is happening

### Why chat-based approval instead of approval packets?

1. **Coherence:** Approval is recorded in the same session as the operator's questions and context
2. **Natural review:** Operator can read preflight summary, ask questions, then approve
3. **No files:** Reduces boilerplate and keeps evidence where the decisions were made
4. **Flexibility:** Approval can reference session context without creating external documents

## Getting Started With Production Access

If you are an operator ready to work on production:

1. Ensure a local production secrets file exists: `terraform/secrets.pve.enc.yaml`
2. Verify SOPS age key: `ls -la ~/.config/sops/age/keys.txt`
3. Test read-only access:
   ```bash
   ./with-secrets-prod pct list
   ```
4. For mutating work:
   - Ask Copilot for a preflight summary of what will change
   - Review the summary carefully
   - Say "proceed" or similar in chat (explicit approval)
   - Copilot will set `TASK_APPROVAL` and run the command
   - Review the after-action summary

## Verified Production Auth Check

The simplest read-only check that proved the current production token works was:

```bash
curl -ks -H "Authorization: PVEAPIToken=automation@pve!terraform=<TOKEN_SECRET>" \
  "https://pve.gibbsgreatly.xyz:8006/api2/json/version"
```

On May 22, 2026, this returned HTTP 200 for the production token stored in
`terraform/secrets.pve.enc.yaml`.

## Related Documentation

- [Task 01: Production Credential Controls](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/01-credential-controls.md)
- [Productionize Refactor Plan](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md)
- [SOPS / Age Key Setup](terraform/README.md)
