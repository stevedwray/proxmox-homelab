# Task 01: Production Credential Controls

## Goal

Design and implement tight controls around any production credential exposure
to an AI-operated environment.

## Why This Comes First

Productionization will eventually require the repo and its automation paths to
understand `pve`. That is useful, but it increases risk if production secrets
can be loaded through the same casual path used for `pve-test`.

This task exists to ensure production access becomes more deliberate before it
becomes more convenient.

## Desired Outcome

- production credentials are not loaded by default
- production read-only access is separated from production mutation access
- production mutation access requires explicit additional approval
- the operator can still use AI for planning and read-only investigation
  without opening the door to accidental destructive changes

## Scope

In scope:

- design of production secret separation
- design of a separate production wrapper or equivalent gate
- read-only vs mutating command policy
- approval and evidence requirements

Out of scope:

- actual production service migration
- network or storage manifest authoring

## Recommended Design Direction

1. Keep `./with-secrets` dev-oriented and `pve-test`-safe.
2. Do not broaden the normal wrapper to load production secrets.
3. Create a separate production access path, likely `./with-secrets-prod`.
4. Use separate encrypted secret storage for production.
5. Require explicit per-task operator approval for mutating production
   commands, but do not require approval packet files.

## Operator Decisions Locked In

The operator has already chosen the initial control model:

- production mutations are approved in the Copilot chat session, not through
  approval packet files
- if the operator asks for a production task to be done, or reviews the session
  preflight summary and says to proceed, that counts as approval for that task
- production mutations still require explicit per-task approval; there is no
  standing blanket approval for `pve`
- production secrets should live in a separate SOPS-encrypted file
- production commands should be classified as read-only vs mutating
- operator summaries and execution evidence should be presented in the Copilot
  chat session

## Concrete Deliverables

- documented production secret separation model
- documented production wrapper behavior
- command-class model for production operations
- documented chat-based approval workflow for mutating production tasks
- chat-based preflight and after-action summary requirements

## Candidate Implementation Shape

- `terraform/secrets.pve-test.enc.yaml`
- `terraform/secrets.pve.enc.yaml`
- `with-secrets` remains default-safe for `pve-test`
- `with-secrets-prod` requires:
  - `PVE_ENV=pve`
  - `TF_VAR_proxmox_node=pve`
  - command classification check
  - explicit per-task operator approval for mutating commands

Recommended first-pass behavior:

- read-only production commands are allowed only through `with-secrets-prod`
- mutating production commands are blocked unless the operator has approved the
  task in chat and has locally acknowledged that approval when invoking the
  mutating command
- no external approval packet file is required

## Command Classes To Define

Production commands are classified into two groups:

### Read-Only Commands (Allowed by default through `with-secrets-prod`)

These commands inspect state only and do not alter production:

**Inventory & status:**
- `pct list`, `qm list` (list containers/VMs)
- `pvesm status` (storage status)
- `pvesh get /api2/json/*` (Proxmox API reads)

**Validation & planning:**
- `terragrunt plan` (plan without apply)
- `terraform plan` (same)
- `terraform validate`
- `terragrunt validate`, `terragrunt show`, `terragrunt output`
- `terraform version`
- `ansible-inventory` dry-runs

**Monitoring & inspection:**
- `dig`, `ping`

Ambiguous tools like `ssh`, `scp`, `curl`, `ansible-playbook`, and custom
scripts should be treated as mutating in the first implementation slice unless
the wrapper has a narrowly defined safe mode for them.

### Mutating Commands (Blocked unless explicit operator approval in session)

These commands alter production state and require pre-approval:

**Infrastructure mutation:**
- `terragrunt apply`, `terraform apply` (any IaC apply)
- `pct create`, `pct destroy`, `pct set` (LXC control)
- `qm create`, `qm destroy`, `qm set` (VM control)
- SDN zone/vnet/vlan creation/deletion
- firewall rule changes
- storage pool changes

**Service deployment/migration:**
- `ansible-playbook` with state-changing tasks
- container start/stop/restart on production
- service cutover operations
- migration of workloads between nodes

**Policy:**
- read-only commands may run through `with-secrets-prod` without additional approval
- mutating commands are blocked with a clear error unless:
  1. the operator has explicitly approved the named task in chat, AND
  2. the operator has locally acknowledged that approval when invoking the
     mutating command after reviewing a preflight summary
- no approval packet files are used; chat confirmation is the approval mechanism

## Files Likely Involved

- [with-secrets](/home/steve/git/proxmox-homelab/with-secrets:1)
- `with-secrets-prod` if introduced
- `terraform/secrets*.enc.yaml`
- docs under `docs/reference/` or this refactor directory

## Dependencies

- none for the design phase
- implementation should land before broad production secret usage

## Approval Flow For Production Mutations

**Before any production mutation:**

1. The session displays a **preflight summary**:
   - target environment (`pve`) and host
   - whether the operation is mutating
   - exact objects expected to be changed
   - specific commands or command class
   - explicit out-of-scope items (what will NOT change)

2. The operator reviews the summary and explicitly confirms in chat:
   - "proceed", "yes", "do it", or similar clear approval
   - or rejects/modifies the plan before approval

3. The session records the approval point in chat and the operator locally
   acknowledges that approval when invoking the mutating command

**After any production mutation:**

1. The session displays an **after-action summary**:
   - what was actually inspected or changed
   - whether anything failed, was skipped, or succeeded
   - confirmation that the resulting state matched expectations
   - any follow-up actions still needed

2. If mutations were blocked (no operator approval), the error message is clear:
   - names the specific command that was blocked
   - names the task requiring approval
   - explains the local acknowledgement step needed after chat approval

**No standing approval:**

- there is no blanket "ALLOW_PVE=true" mode that permits all mutations
- each task requiring mutations must have explicit per-task operator approval
- changing the approval does not auto-apply previous approvals to new tasks
- even after one mutation is approved, the next different mutation requires new approval

## Risks

- partial implementation could create a false sense of safety
- mixing prod and dev secrets in one wrapper increases accidental-target risk
- operator convenience pressure may weaken the controls unless the design is
  explicit and tested
- relying on chat-session approval means the implementation must be very clear
  about when a command is classified as mutating

## Suggested Branch

- `work/productionize-01-credential-controls`
