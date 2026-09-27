# Secrets Management Design: Moving Off Branch-Coupled SOPS

## Status

**Decision:** Adopt OpenBao as the authoritative secrets store.

**Current state:** SOPS-encrypted YAML files stored in the main Git repository.

**Target state:** Secret values exist only in OpenBao. Git contains configuration and secret references, but never authoritative secret values.

This design covers:

- deployment of OpenBao;
- handling of the OpenBao seal key;
- common, host-specific, and service-specific secret scopes;
- access by Proxmox hosts, containers, and application stacks;
- human authentication through Authentik;
- replacement of the existing `with-secrets` / `with-secrets-prod*` workflow;
- migration from the existing SOPS files;
- backup and recovery requirements;
- security boundaries and acceptance criteria.

High availability, dynamic secrets, PKI, and broader credential-rotation automation are not required for the initial migration.

## Operator decisions (2026-09-28)

These were settled in design review and are reflected throughout the document:

| Decision | Choice | Where |
| --- | --- | --- |
| Deploy-time authentication for `with-secrets` (operator and agents on the workstation) | Read-only AppRole per environment; no Authentik dependency on the deploy path | §12, §14, §16 |
| Human authentication | Authentik OIDC for the UI and for secret writes only | §17–19 |
| USB seal key after unseal | Left inserted; fully unattended unseal | §8 |
| SOPS → OpenBao cutover | Reconcile against live, bulk import, switch wrapper backend wholesale, freeze SOPS files | §20 |
| CI secret access | OpenBao JWT auth trusting GitHub Actions OIDC tokens | §14.2 |
| KV layout | KV v2, one entry per service, field names = existing env var names | §10, §11 |

Real Proxmox node names are used throughout (`pve`, `pve-tiny`, `pve-test-vm`, `pve-test`), taken from `terraform/PRODUCTION_NODES` and the existing `terraform/secrets.<node>.enc.yaml` files. `pve-framework` is no longer a Proxmox node, but it still has a secrets file that must be inventoried.

---

# 1. Problem

Secrets currently live as SOPS-encrypted YAML committed to the main Git repository, including:

```text
terraform/secrets.common.enc.yaml
terraform/secrets.<node>.enc.yaml
```

These files are encrypted at rest but are nevertheless ordinary Git-controlled files.

This creates a fundamental coupling between:

```text
Git branch state
        │
        ▼
encrypted secret file state
        │
        ▼
deployed secret value
```

As a result, ordinary Git operations can unintentionally change the effective secret state.

This has caused repeated real incidents.

Examples include:

- checking out a branch created before a password rotation and silently restoring the old password;
- independently modifying the same SOPS document on different branches and encountering ciphertext-level merge conflicts;
- having to decrypt competing versions out-of-band to determine the intended secret values;
- authentication subsequently failing with symptoms such as HTTP 401 responses, with no indication that a Git checkout caused the credential rollback.

The Graylog root password incidents of September 2026 demonstrated that this is not merely a theoretical inconvenience.

The problem is therefore not primarily SOPS encryption itself.

The architectural problem is:

> **Git is acting as the transport and version authority for mutable secret values.**

---

# 2. Core Design Principle

A secret value is not an inherent property of a Git branch.

A secret belongs to:

1. the service, host, or workload that consumes it; and
2. the secrets store that is authoritative for its current value.

Once a secret has been deployed or rotated, unrelated operations such as:

```text
git checkout
git switch
git merge
git rebase
git reset
```

must not be capable of reverting or changing that secret.

Git may contain:

- secret names;
- secret paths;
- configuration describing which secret a service requires;
- OpenBao policies;
- OpenBao role definitions;
- deployment automation.

Git must not contain the authoritative secret values themselves.

The required architectural property is:

```text
git checkout old-branch
        │
        ├── code may change
        ├── configuration may change
        ├── secret references may change
        │
        └── secret values in OpenBao DO NOT CHANGE
```

---

# 3. Options Considered

## 3.1 Smaller SOPS files

Splitting the current files into smaller per-service SOPS files would reduce merge collisions.

It does not address the underlying issue.

A branch can still contain an old encrypted value and a checkout can still restore it.

**Decision:** Rejected.

---

## 3.2 SOPS-aware Git merge handling

A semantic merge driver could decrypt competing files and perform a structured merge.

This would make merges less painful but would not prevent branch checkouts from selecting historical secret state.

**Decision:** Rejected.

---

## 3.3 Separate SOPS repository or untracked secret files

Moving encrypted secrets outside the application repository would remove direct branch coupling.

It would introduce a second synchronization mechanism and create new opportunities for stale local state.

The secrets would still fundamentally be files that must be distributed and synchronized.

**Decision:** Rejected.

---

## 3.4 HashiCorp Vault

Vault provides the required architecture but its licensing change means it is no longer the preferred option for this environment.

**Decision:** Rejected.

---

## 3.5 Infisical

Infisical remains technically viable.

It provides:

- central secrets storage;
- workload identities;
- self-hosting;
- a good application/developer integration model.

It also avoids Vault/OpenBao's traditional seal/unseal model.

However, once OpenBao's native static-key auto-unseal is taken into account, the operational difference is smaller than originally assumed.

Infisical also introduces its own persistent application infrastructure and bootstrap secrets.

**Decision:** Not selected.

---

# 4. Selected Solution: OpenBao

OpenBao will become the authoritative secrets manager.

The initial deployment will use:

- one OpenBao instance;
- a dedicated LXC;
- OpenBao Integrated Storage using Raft;
- TLS for client connections;
- native static-key auto-unseal;
- a removable USB device as the physical storage location for the static seal key;
- Authentik OIDC for normal human access;
- AppRole or equivalent machine authentication for automated consumers.

OpenBao's Integrated Storage is a native storage backend that does not require an external database and supports snapshot-based backup and restore.

The initial architecture intentionally remains single-node. OpenBao supports expanding Raft into a multi-node deployment later, but high availability is not required to resolve the SOPS/Git problem.

---

# 5. High-Level Architecture

```text
   ┌─────────────┐   OIDC (UI + writes only)
   │  Authentik  │◄──────────────────────────┐
   └─────────────┘                           │
                                             │
                        ┌────────────────────┴─┐
                        │     OpenBao LXC      │
                        │       (on pve)       │
USB seal key ──────────►│ static auto-unseal   │
(host bind mount)       │ integrated Raft      │
                        │ KV v2 secrets        │
                        │ policies / AppRoles  │
                        │ JWT auth (GitHub)    │
                        └──────────┬───────────┘
                                   │ HTTPS (direct, not via Traefik)
          ┌────────────────────────┼─────────────────────────┐
          │                        │                         │
          ▼                        ▼                         ▼
 operator workstation      self-hosted CI runner      (later) workloads that
 with-secrets / -prod*     netbox-populate etc.       pull their own secrets
 read-only AppRole         JWT / GitHub OIDC          per-service AppRole or
 per environment                                      OpenBao Agent
          │
          │ push: terraform / ansible / compose
          ▼
   pve, pve-tiny, pve-test-vm, … → stacks (rendered .env on target, as today)
```

Today, deployment is **push-based**. The workstation runs `with-secrets` and pushes to the nodes. The Proxmox hosts do not fetch secrets themselves. The design keeps this model. The primary OpenBao consumers are therefore the workstation (one read-only identity per target environment) and CI. Per-host and per-workload identities are introduced only for workloads that are later changed to pull their own secrets (§15).

OpenBao is a service shared by the whole Proxmox environment. Access policy keeps the secret scopes separated.

Separate secret files or separate OpenBao instances are not required merely because different Proxmox hosts have different secrets.

---

# 6. OpenBao Deployment

OpenBao will run in a new dedicated LXC.

The LXC will be deployed using the same infrastructure/deployment approach used for other managed services in the repository.

The exact playbook and inventory integration will be defined in the implementation step packet.

Conceptually:

```text
Proxmox
   │
   └── OpenBao LXC
         ├── OpenBao server
         ├── /etc/openbao/
         ├── /var/lib/openbao/
         │      └── raft/
         └── HTTPS listener
```

Integrated Raft storage will be used rather than adding PostgreSQL or another external persistence layer. OpenBao documents Integrated Storage as the normal self-contained storage option and recommends it for most deployments.

The initial cluster consists of a single Raft member.

This design does not prevent additional OpenBao nodes from being introduced later if availability requirements change.

## 6.1 Placement and network dependencies

- **Host:** `pve`. The USB seal key must be physically attached to the host that runs the LXC.
- **Access path:** clients connect to the OpenBao HTTPS listener directly. It must **not** be routed through Traefik or Authentik forward-auth. Otherwise a Traefik or Authentik outage would block the secrets reads needed to redeploy Traefik or Authentik.
- **Addressing:** `BAO_ADDR` must work by IP as well as by FQDN, so that a Technitium outage does not block secret reads. Clients pin the CA that issued the listener certificate.
- **TLS certificate:** issued by step-ca, with renewal that does not depend on any secret stored in OpenBao. The exact issuance mechanism will be defined in the implementation plan.

Every dependency OpenBao needs in order to start must either avoid OpenBao-held secrets or be covered by the bootstrap kit (§9.1).

---

# 7. Seal Key Design

## 7.1 Static auto-unseal

The original design assumed that OpenBao would require Shamir key shares to be supplied automatically after every restart.

That is unnecessary.

OpenBao has a native `static` seal mechanism which accepts a 32-byte AES key, including from a file using the `file://` mechanism. It acts as an auto-unseal mechanism without requiring a second Vault/OpenBao installation or a cloud KMS.

Conceptually:

```hcl
seal "static" {
  current_key_id = "lab-2026-01"
  current_key    = "file:///path/to/openbao-seal.key"
}
```

The actual paths and identifiers will be defined by the deployment implementation.

The static seal therefore replaces the previously proposed systemd process that would execute:

```text
bao operator unseal <share>
bao operator unseal <share>
bao operator unseal <share>
```

No Shamir shares need to be stored together on the host.

**Verify before relying on it:** the static seal is a relatively recent OpenBao feature. Phase 1 must confirm that the OpenBao release being deployed supports `seal "static"` with a `file://` key. It must also confirm the exact config syntax against that release's documentation, rather than trusting the example above.

---

# 8. USB-Backed Seal Key

The static seal key will be stored on removable USB media rather than persisted alongside the OpenBao data.

The intended trust boundary is:

```text
OpenBao Raft data
        │
        │ cannot decrypt itself
        ▼

USB seal key
        │
        │ supplied when OpenBao must unseal
        ▼

running OpenBao
```

The USB device is mounted by the Proxmox host (`pve`), not managed directly by OpenBao.

The key reaches the OpenBao LXC through a **host bind mount** (`mpN: /host/path,mp=/container/path`) that exposes only the key file's directory, read-only. It is never copied onto the container's own rootfs or volumes. Implementation notes:

- A bind mount into an LXC can only be configured as `root@pam` over SSH (`pct set`), not through an API token.
- In an unprivileged LXC, the key file must be readable by the container's mapped UID (subuid 100000 + the OpenBao service UID), not by host root.

**Operating model (decided): the USB stays inserted.**

```text
host boot
   │
   ▼
host mounts USB (fstab / systemd mount unit, nofail)
   │
   ▼
OpenBao LXC starts → reads static seal key via bind mount
   │
   ▼
OpenBao auto-unseals, unattended
```

Host reboots, power loss, LXC restarts and OpenBao upgrades all recover without an operator present. Deploys and CI are therefore never blocked because nobody was around to supply the key.

The USB is removed only deliberately, for example to move it to another host or to rotate the key.

If the USB is missing at boot, OpenBao stays sealed and reports that clearly. The host must still boot, so the mount must be `nofail`.

OpenBao's documentation explicitly warns that the static seal key must be treated as an independent source of trust and protected appropriately.

## 8.1 Trust model

With the USB left inserted, the seal key's job is **separating the key from the data**, not physical-presence gating. It protects against:

- an OpenBao Raft snapshot containing everything needed to decrypt itself;
- a `vzdump` backup of the OpenBao LXC containing the seal key. This holds only because the key arrives by host bind mount, which `vzdump` skips. Phase 1 must verify this by inspecting a real backup of the LXC.
- the seal key accidentally ending up in Git;
- routine filesystem rollback or snapshot of the OpenBao instance.

It does **not** protect against:

- a compromised Proxmox root account on `pve`;
- physical theft of the `pve` host with the USB attached. Whoever takes the machine gets both the data and the key.

These are accepted for this environment. The existing SOPS implementation has the same exposure: the age key sits on the workstation, next to the ciphertext it decrypts.

---

# 9. Seal Key Backup

The USB device must not be the only copy of the static seal key.

At least one additional offline copy must exist.

Conceptually:

```text
USB A
    operational seal key

USB B
    offline recovery copy
```

The copies should be stored separately.

Loss of:

```text
OpenBao data
```

is recoverable from a Raft snapshot.

Loss of:

```text
seal key
```

without another valid copy can make otherwise intact OpenBao data unrecoverable.

Therefore:

> An OpenBao backup consists logically of both a Raft backup and the seal-key material required to decrypt that generation of data.

OpenBao's static seal mechanism supports current and previous keys during key rotation.

Old seal keys must not be destroyed until backups that depend on them have expired or been replaced.

With the operational USB permanently attached to `pve`, the offline copy (USB B) is the only copy that survives theft or failure of that host. USB B must be stored away from `pve`.

## 9.1 Bootstrap kit

OpenBao cannot hold the secrets needed to rebuild OpenBao itself. The OpenBao LXC is created by Terraform using `TF_VAR_pm_api_token_secret` and `TF_VAR_lxc_password`. If those values lived only in OpenBao, losing the OpenBao LXC or `pve` would leave no way to recreate it.

A small, explicitly enumerated **bootstrap kit** is therefore kept outside OpenBao:

- It contains only what is needed to recreate the OpenBao LXC and restore a snapshot onto it: the `pve` Proxmox API token, the LXC root password, and the OpenBao recovery keys (§19). The exact list is fixed in the implementation plan and reviewed whenever OpenBao's own deployment changes.
- It is age-encrypted to the operator's key and never committed to Git.
- It is stored with the offline seal-key copy (USB B), with a second copy in Bitwarden.
- The values it holds also exist in OpenBao, and OpenBao is authoritative for them. Whenever one of them is rotated, the kit must be regenerated. The rotation runbook for those specific secrets includes that step.

The bootstrap kit is a recovery artifact, not a second deployment path. `with-secrets` never reads it.

---

# 10. Secret Scope Model

The current repository has an important distinction between:

- common secrets; and
- secrets specific to individual Proxmox nodes.

That distinction remains valid.

What changes is how it is represented.

Instead of:

```text
secrets.common.enc.yaml
secrets.pve.enc.yaml
secrets.pve-tiny.enc.yaml
secrets.pve-test-vm.enc.yaml
...
```

the distinction becomes OpenBao path structure.

The secrets engine is **KV version 2**, mounted at `kv/`. KV v2 keeps a version history for every entry. That turns recovery from a bad rotation into an explicit `bao kv rollback`, instead of the Git archaeology the September 2026 Graylog incidents required. KV v2's check-and-set option also prevents lost updates when two operators write the same entry.

**One KV entry per service, with field names equal to the existing environment variable names.** The current keys already group cleanly by prefix (HARBOR ×9, NETBOX ×8, MIKROTIK ×8, NEXTCLOUD ×6, …). For example:

```text
kv/services/harbor      → { HARBOR_DB_PASSWORD: …, HARBOR_ADMIN_PASSWORD: …, HARBOR_ROBOT_USER: …, … }
kv/services/graylog     → { GRAYLOG_ROOT_PASSWORD: …, GRAYLOG_ROOT_PASSWORD_SHA2: … }
kv/hosts/pve            → { TF_VAR_pm_api_token_secret: …, TF_VAR_lxc_password: …, PROXMOX_READONLY_TOKEN_ID: …, … }
```

This keeps `with-secrets` trivial: it reads a list of paths and exports every field under its own name. A run needs about 30 reads instead of 115. Values that are rotated together, such as a password and its hash, also live in one entry, so they change in a single versioned write.

The initial logical structure will be:

```text
kv/
├── services/
│   ├── authentik
│   ├── graylog
│   ├── harbor
│   ├── netbox
│   ├── wazuh
│   └── ...
│
├── hosts/
│   ├── pve
│   ├── pve-tiny
│   ├── pve-test-vm
│   ├── pve-test
│   └── ...
│
└── shared
```

These represent three different scopes.

## 10.1 Service-scoped secrets

A secret belongs here when its identity comes from the service rather than the host.

For example:

```text
kv/services/graylog     GRAYLOG_ROOT_PASSWORD, GRAYLOG_ROOT_PASSWORD_SHA2
kv/services/harbor      HARBOR_ROBOT_USER, HARBOR_ROBOT_PASSWORD, …
kv/services/authentik   AUTHENTIK_SECRET_KEY, …
```

A password used by Graylog remains a Graylog secret even if several machines consume it.

---

## 10.2 Host-scoped secrets

A secret belongs here when the value is genuinely unique to a particular Proxmox server or workload running on it.

For example:

```text
kv/hosts/pve        TF_VAR_pm_api_token_secret, TF_VAR_lxc_password, PROXMOX_READONLY_TOKEN_ID, PROXMOX_READONLY_TOKEN_SECRET
kv/hosts/pve-tiny   …
```

In practice this scope holds each node's Proxmox API identity and its LXC root password, which is exactly what the per-node SOPS files hold today (2–5 keys each).

Host-specific secrets remain independently manageable.

Changing the value associated with one host does not change another host.

---

## 10.3 Shared secrets

Some secrets may genuinely be shared across unrelated services or hosts.

Those can remain conceptually equivalent to the current common secret set:

```text
kv/shared/<secret>
```

However, migration should not mechanically transform:

```text
secrets.common.enc.yaml
```

into:

```text
kv/shared/
```

Every existing common secret should first be classified.

Many values that are currently "common" because they were convenient to place in a common YAML document may actually be service-scoped.

---

# 11. Git Representation

Git will retain only references to secrets.

The references live in a single tracked manifest. It tells `with-secrets` which KV entries to read for each environment:

```yaml
# secrets/manifest.yaml (illustrative; exact location fixed in the plan)
common:            # read for every environment
  - services/authentik
  - services/graylog
  - services/harbor
  - shared
  # ...
environments:
  pve:         [hosts/pve]
  pve-tiny:    [hosts/pve-tiny]
  pve-test-vm: [hosts/pve-test-vm]
  pve-test:    [hosts/pve-test]
```

This reproduces today's "common, plus the per-node file merged on top" behaviour, with no separate name-mapping layer. The exported variable names are the KV field names, so `TF_VAR_*` naming continues unchanged.

The manifest is branch-dependent, and that is fine. A branch can change *which* entries are read. It cannot change the values in them.

Git must not contain:

```yaml
graylog:
  root_password: actual-password
```

Git also contains the OpenBao policy, auth-role and mount definitions, because they describe authorization rather than secret values. They are applied by the implementation's configuration step, not by hand in the UI.

---

# 12. Access Control

OpenBao access will default to deny.

Policies will grant consumers only the paths required for their role.

The initial identities follow the boundary that actually exists today: **one read-only deploy identity per target environment**. These are held on the operator workstation and selected by the wrapper.

```text
deploy-dev            (used by ./with-secrets)
READ:      kv/services/*, kv/shared, kv/hosts/pve-test-vm, kv/hosts/pve-test
NO ACCESS: kv/hosts/<any production node>

deploy-<prod-node>    (one per line in terraform/PRODUCTION_NODES; used by that node's ./with-secrets-prod* wrapper)
READ:      kv/services/*, kv/shared, kv/hosts/<prod-node>
NO ACCESS: kv/hosts/<every other node>

ci-netbox-populate    (GitHub Actions via JWT, §14.2)
READ:      only the entries that workflow needs
```

Service values are the same for dev and production today, because the common file is shared. That stays true, and both identity classes can read `kv/services/*`.

Production separation stays where it is now. Only the prod-node identity can read a node's Proxmox API token and LXC root password. The `with-secrets-prod*` command classifier and `TASK_APPROVAL` gate stay in the wrapper, unchanged. OpenBao does not replace that process control. It makes "which node's credentials can this identity read" an enforced policy rather than a matter of which file got loaded.

New production nodes are onboarded by adding a line to `terraform/PRODUCTION_NODES`. The policy and role for `deploy-<node>` are generated from that file, never hand-written per node.

Workloads that are later moved to pull their own secrets (§15) get narrower per-service identities. For example, a Graylog workload identity would read only `kv/services/graylog` and would have no access to any other service's entry.

---

# 13. Secret Mutation

An important property of the new design is that routine deployment must not be able to overwrite secret values.

Deployment and secret rotation are distinct operations.

Normal deployment tooling should generally have:

```text
READ secret
```

but not:

```text
CREATE secret
UPDATE secret
DELETE secret
DESTROY secret
```

This ensures that even if an old Git branch contains an obsolete secret reference or obsolete configuration, running the deployment cannot revert the OpenBao secret itself.

Only explicitly privileged operator/rotation identities will have write permission.

This turns the core design principle into an enforced authorization boundary rather than relying only on process discipline.

## 13.1 Keeping write tokens away from agents

Coding agents (Claude Code, Copilot/local models) run commands as the operator's Unix user. They can read anything the operator's shell can, including a token cached at the default `~/.vault-token` path. If the operator's OIDC write-capable token sat there, any agent session could `bao kv put`, and the read-only deploy boundary would be bypassed without anyone noticing.

Therefore:

- `with-secrets` authenticates **only** with the read-only AppRole for the selected environment. It fetches a short-lived token per invocation, passes it only to its own process, and never writes it to disk.
- A human write session is a deliberate, separate step. The operator logs in by OIDC with `login -no-store` and exports the resulting token only into that shell's environment, so it is never persisted to the default token file. Vault's CLI has `-no-store`; Phase 2 must confirm that OpenBao's `bao` CLI still has the equivalent. The write token's TTL is short (such as 1h) and it cannot be renewed past that.
- Rotation helper scripts require an explicitly supplied write token. They never fall back to a cached one.

This keeps the property the SOPS workflow had in practice, where agents could read secrets through the wrapper but could not change them. That property now comes from policy rather than from the agent harness happening to block SOPS writes.

---

# 14. Machine and Workload Authentication

OpenBao supports AppRole specifically for applications and automated workflows. An AppRole can represent anything from a machine to a single workload and issues OpenBao tokens carrying configured policies.

This will be the initial machine-authentication mechanism unless a particular consumer has a more suitable native OpenBao/Vault authentication mechanism.

The authentication model is:

```text
workload
   │
   │ RoleID + protected bootstrap credential
   ▼
AppRole login
   │
   ▼
short-lived OpenBao token
   │
   ▼
allowed secret paths
```

This still creates a small "secret zero" problem: the workload needs sufficient bootstrap material to authenticate.

That material is local operational state and must not be stored in Git.

## 14.1 Workstation deploy identities

The `deploy-dev` and `deploy-<prod-node>` AppRoles (§12) are the workstation's secret zero. Each role's RoleID and SecretID take the place of `~/.config/sops/age/keys.txt` and are handled the same way:

- stored under `~/.config/openbao/` at mode 0600, one file per role;
- backed up in Bitwarden, as the age key is today;
- given a long-lived SecretID, with the issued tokens short-lived (for example, 15-minute TTL, not renewable beyond one `with-secrets` run);
- optionally bound to the workstation's LAN address with `secret_id_bound_cidrs`.

The deploy path does not depend on Authentik. If Authentik is down, `./with-secrets-prod scripts/provision.sh --stack authentik-stack` still works.

## 14.2 CI (GitHub Actions)

CI workflows that need secrets (currently `netbox-populate.yml` and the `sops-decrypt-check` job in `validate.yml`, both on the self-hosted runner) authenticate using OpenBao's **JWT auth method trusting GitHub's Actions OIDC issuer**:

- The role is bound to this repository. It is additionally bound by claims such as `job_workflow_ref` or `ref`, so that only the intended workflow on the intended branch can log in.
- Each role has its own narrow read-only policy.
- No long-lived OpenBao credential is stored in GitHub.

The existing operator policy still applies: secrets are only ever retrieved on the self-hosted runner, never on GitHub-hosted runners. The runner must be able to reach OpenBao directly. GitHub's token endpoint is contacted by the runner, not by OpenBao, because OpenBao only needs GitHub's public JWKS to validate tokens.

The `sops-decrypt-check` job becomes an OpenBao reachability and read check, or is removed. Once no workflow uses `SOPS_AGE_KEY`, that GitHub secret is deleted.

It is nevertheless substantially better than storing every long-lived application credential in Git.

---

# 15. Direct Container and Stack Access

Containers and stacks may access OpenBao themselves when they need secrets.

This is a target capability, not a requirement that every existing application be converted immediately.

Three integration patterns are supported.

---

## 15.1 Native OpenBao/Vault integration

Applications that already support the Vault API can authenticate directly.

```text
application
     │
     │ HTTPS
     ▼
OpenBao
     │
     ▼
secret
```

This is the preferred model where the application already has appropriate support.

---

## 15.2 OpenBao Agent / rendered secret

Applications that cannot communicate with OpenBao directly can use an intermediary which retrieves the secret and makes it available in the format expected by the application.

Conceptually:

```text
OpenBao
   │
   ▼
OpenBao Agent
   │
   ▼
/run/secrets/<name>
   │
   ▼
application
```

This allows an application to continue reading an ordinary file without knowing that OpenBao exists.

---

## 15.3 Deployment-time injection

Existing deployment tooling can continue retrieving secrets immediately before starting a stack.

```text
deployment wrapper
       │
       ▼
OpenBao
       │
       ▼
temporary env/file
       │
       ▼
docker compose / terraform / ansible
```

This will be the migration bridge for the existing `with-secrets` workflow.

---

# 16. Replacing `with-secrets`

The existing user-facing workflow does not need to change during the initial migration.

Commands such as:

```text
with-secrets
with-secrets-prod
with-secrets-prod*
```

can remain.

Their backend behaviour changes.

Current behaviour:

```text
with-secrets
     │
     ▼
locate SOPS file
     │
     ▼
decrypt YAML
     │
     ▼
export variables
     │
     ▼
execute requested command
```

Target transitional behaviour:

```text
with-secrets
     │
     ▼
load .env / .env.<PVE_ENV> (unchanged)
     │
     ▼
AppRole login as deploy-<environment> (§14.1)
     │
     ▼
read manifest entries: common + environments[PVE_ENV] (§11)
     │
     ▼
fail closed if any entry is missing, or any field is empty
     │
     ▼
export fields (host entries override common, as today)
     │
     ▼
execute requested command
```

Specific requirements:

- **Fail closed on empty values.** `scripts/check-required-sops-keys.sh` exists because `HARBOR_DB_PASSWORD` was silently wiped to `""` and took down `harbor-stack` five days later. The wrapper must refuse to run if any manifest entry cannot be read or contains an empty field. It must never export a blank value.
- **Unchanged safety rails.** The `PRODUCTION_NODES` refusal, the `ALLOW_PVE` override, the `LAB_DOMAIN` contamination guard, and the `with-secrets-prod*` command classifier and `TASK_APPROVAL` gate all keep working exactly as they do now.
- **Backend flag for rollback.** `SECRETS_BACKEND=sops` selects the legacy SOPS path for the duration of the cutover window (§20). The default becomes `openbao` at cutover. The flag and the SOPS code path are removed at retirement (§25).
- **Nothing written to disk.** As today, secret values exist only in the child process environment.

This allows migration of the secret backend without simultaneously rewriting every Terraform, Ansible, Docker, or operational invocation.

Individual workloads can subsequently move to direct OpenBao access where doing so is useful.

There is no requirement to remove the wrapper merely for architectural purity.

---

# 17. Human Authentication

Normal human interaction with OpenBao will use Authentik. This covers **the UI and secret writes (rotation) only**. Deploy-time reads use the AppRole identities in §14.1, and those never depend on Authentik. This breaks the circular dependency that would otherwise exist: Authentik's own secrets live in OpenBao, so redeploying a broken Authentik must not require logging in through Authentik.

OpenBao supports OIDC authentication for both its UI and CLI, including a browser-based OpenBao UI login flow.

The authentication path becomes:

```text
Browser
   │
   ▼
OpenBao UI
   │
   │ OIDC
   ▼
Authentik
   │
   ▼
user / group claims
   │
   ▼
OpenBao identity
   │
   ▼
OpenBao policy
```

The OpenBao UI callback has the documented form:

```text
https://<openbao-host>/ui/vault/auth/<oidc-mount>/oidc/callback
```


The expected default mount would make this:

```text
https://<openbao-host>/ui/vault/auth/oidc/oidc/callback
```

---

# 18. Authentik Group Mapping

Where practical, Authentik groups will represent human roles.

For example:

```text
Authentik                     OpenBao

openbao-admins      ───────►  administrative policy

openbao-operators   ───────►  operational secret access

openbao-readers     ───────►  restricted read access
```

The final group names will follow the existing Authentik naming conventions rather than being imposed by this design.

Human authorization remains controlled by OpenBao policies.

Authentik proves identity and supplies group/identity claims; it does not become the secret store itself.

---

# 19. Break-Glass Access

Authentik must not become the only possible way to administer OpenBao.

If Authentik is unavailable or its OIDC configuration is damaged, OpenBao still needs an administrative recovery mechanism.

Because the static seal is an auto-unseal mechanism, `bao operator init` produces **recovery keys**, not unseal keys. The recovery keys cannot unseal OpenBao. They authorize privileged operations such as `bao operator generate-root`.

The break-glass procedure is therefore:

1. At initialization, the recovery keys are stored in the bootstrap kit (§9.1) and in Bitwarden.
2. The initial root token is used only to apply the first configuration (auth methods, policies, mounts), and is then **revoked**. No standing root token exists.
3. If Authentik is unavailable and an administrative change is needed, a new root token is generated with `generate-root` and the recovery keys. It is used for the minimum change needed, then revoked.

Most Authentik outages do not need break-glass at all. Deploy-time reads continue through AppRole (§14.1), so redeploying Authentik works normally. Break-glass is only for administrative changes to OpenBao itself while OIDC is unavailable, for example repairing the OIDC auth configuration.

Normal administration should occur through Authentik OIDC.

---

# 20. Migration Strategy

**The source of secret values switches all at once. Consumers move to direct access gradually.**

A per-secret incremental switch was considered and rejected. It would leave a window in which some values are authoritative in SOPS and some in OpenBao, with a wrapper reading from both. During that window, a rotation made on a stale branch could still land in SOPS. That is exactly the failure mode this design exists to remove.

Instead:

1. Build OpenBao and its auth alongside SOPS (Phases 1–3). SOPS remains the only live backend.
2. Inventory and reconcile (Phase 4): establish the correct current value of every secret, checked against the running services, not against whichever branch happens to be checked out.
3. **Cutover** (Phase 5): import everything in one pass, switch the `with-secrets` default backend, and freeze the SOPS files.
4. Move individual consumers to direct access over time (§24). This part stays incremental.
5. Retire SOPS (§25) after the recovery test passes.

---

## Phase 0 — Verification spikes

Before building anything, confirm the claims this design depends on against the actual OpenBao release to be deployed:

- the `static` seal accepts a `file://` key (§7);
- `login -no-store`, or its equivalent, exists in the `bao` CLI (§13.1);
- JWT auth works against GitHub's Actions OIDC issuer (§14.2).

This can be done in a throwaway LXC on `pve`.

---

## Phase 1 — Deploy OpenBao

Create the OpenBao LXC and deploy:

- OpenBao;
- TLS configuration;
- Integrated Raft storage;
- static seal configuration;
- USB seal-key handling: host mount unit, read-only bind mount into the LXC;
- offline seal-key copy (USB B);
- bootstrap kit (§9.1), including the recovery keys from initialization;
- initial administrative access.

Verify:

```text
OpenBao auto-unseals from the USB key with no operator action
OpenBao auto-unseals again after an LXC restart, and after a pve host reboot
with the USB absent at boot: host still boots; OpenBao stays sealed and reports why
a vzdump backup of the OpenBao LXC does not contain the seal key
API responds by FQDN and by IP, with the pinned CA
UI responds
initial root token revoked after initial configuration
```

---

## Phase 2 — Configure human authentication

Configure:

- Authentik OIDC provider/application;
- OpenBao OIDC auth method;
- group mappings;
- operator policies;
- break-glass recovery procedure.

Verify:

```text
UI login through Authentik works; group claims map to the expected policies
a CLI OIDC login token is not persisted to the default token file (§13.1)
break-glass: generate-root using the recovery keys works, and the resulting token is revoked afterwards
```

---

## Phase 3 — Configure machine authentication

Enable AppRole and JWT auth.

Create the `deploy-dev` and `deploy-<prod-node>` roles and policies, generated from `terraform/PRODUCTION_NODES` (§12). Create the CI JWT role (§14.2). Install the workstation RoleID/SecretID files (§14.1).

Verify:

```text
each deploy identity can read its manifest entries
no deploy identity can create, update, delete or destroy any entry
deploy-dev cannot read kv/hosts/pve (or any other production node)
deploy-pve cannot read kv/hosts/pve-tiny, and vice versa
deploy reads succeed while Authentik is stopped
the CI JWT role can log in only from the bound workflow/ref
```

---

## Phase 4 — Inventory existing SOPS secrets

Inventory:

```text
secrets.common.enc.yaml
secrets.<node>.enc.yaml
```

Every value will be classified as one of:

```text
SERVICE
HOST
SHARED
```

The migration inventory should record:

```text
current SOPS source
current variable/key name
consumer
scope
OpenBao target path
migration status
```

No values need to be included in the migration document itself.

The inventory also covers **code** that references SOPS, not only keys. Today that includes:

- `with-secrets`, `scripts/with-secrets-prod-lib.sh`, `scripts/merge-sops-env.sh`;
- `scripts/check-required-sops-keys.sh` and `.pre-commit-config.yaml`;
- the preflight scripts (`scripts/preflight-production-*.sh` / `.py`), `scripts/setup-dev-env.sh` and `scripts/deploy-phase-04.sh`;
- `.github/workflows/validate.yml` and `.github/workflows/netbox-populate.yml`;
- the playbooks and roles under `ansible/` and `terraform/lxc/ansible/` that mention SOPS;
- the NetBox integrations data in `terraform/lxc/stacks/netbox-stack/integrations/flows.py`.

The implementation plan regenerates this list with a `grep` at execution time, rather than trusting this snapshot.

**Reconciliation.** The value to import for each key is established from the running service where that can be checked (a login or API call using the value), not assumed from the SOPS copy on any one branch. Before import, `stable`'s decrypted values are compared against every other live branch that touches `terraform/secrets.*.enc.yaml`, and any disagreement is resolved explicitly by the operator.

---

## Phase 5 — Cutover

1. Import every reconciled value into its KV v2 entry, using a write identity (§13.1).
2. Run `with-secrets` in OpenBao mode against every environment. Confirm that the exported variable set matches the SOPS-mode export exactly: same names, same values, compared by hash and never printed.
3. Switch the default to `SECRETS_BACKEND=openbao`.
4. **Freeze SOPS.** A pre-commit hook and a CI check reject any change to `terraform/secrets.*.enc.yaml`. From this point, a stale branch cannot reintroduce a changed SOPS value, because nothing reads SOPS by default and the files cannot change.
5. Run a representative provision under the normal production approval flow (for example, one Harbor consumer and `graylog-stack`) to confirm consumers behave identically.

The rollback path is `SECRETS_BACKEND=sops`. It is valid only until the first rotation made in OpenBao after cutover. After that, SOPS holds stale values and must not be used.

---

# 21. Common Secret Migration

For each entry currently in:

```text
secrets.common.enc.yaml
```

determine whether it is genuinely shared.

For example:

```text
GRAYLOG_ROOT_PASSWORD
```

is likely to become:

```text
kv/services/graylog   (field GRAYLOG_ROOT_PASSWORD)
```

rather than:

```text
kv/shared             (field GRAYLOG_ROOT_PASSWORD)
```

Something genuinely consumed across otherwise unrelated workloads can remain:

```text
kv/shared/<name>
```

The purpose of this classification is ownership, not merely reorganizing file names.

---

# 22. Per-Node Secret Migration

Existing per-node files map naturally to host scope where the values are genuinely host-specific.

For example:

```text
secrets.pve.enc.yaml
```

may produce:

```text
kv/hosts/pve
```

while:

```text
secrets.pve-tiny.enc.yaml
```

may produce:

```text
kv/hosts/pve-tiny
```

`secrets.pve-framework.enc.yaml` needs an explicit decision. `pve-framework` is no longer a Proxmox node (it is now bare-metal Ubuntu), so its values are either migrated to whatever scope their current consumer needs, or dropped as dead.

A value located in a per-node file solely because that was convenient does not have to remain host-scoped.

Classification is based on actual ownership and consumption.

---

# 23. Migrate `with-secrets`

This happens as part of the Phase 5 cutover (§20). Once the required values have been imported into OpenBao, change the existing wrapper to retrieve them from OpenBao rather than SOPS, as specified in §16.

Do not simultaneously change unrelated deployment behaviour.

The purpose of this step is strictly:

```text
SOPS read
   ↓
OpenBao read
```

Variable names and consumer interfaces should remain unchanged unless a separate change explicitly requires otherwise.

This keeps the migration small and makes regressions easier to diagnose.

---

# 24. Migrate Individual Consumers

After the compatibility wrapper is proven, workloads can be considered individually for direct OpenBao access.

Possible end states include:

```text
native Vault/OpenBao client
```

or:

```text
OpenBao Agent → /run/secrets/*
```

or simply retaining:

```text
with-secrets → OpenBao
```

where deployment-time secret retrieval remains adequate.

Direct access is therefore an available capability rather than a mandatory refactor.

---

# 25. Retire SOPS Secret Values

SOPS files are removed from active use only after all consumers of their values have been migrated and verified, **and** the recovery test (§27.1) has passed.

Before removal, verify that:

- no deployment scripts still read the file;
- no Terraform or Ansible code expects the SOPS source;
- no operational wrapper references it;
- OpenBao contains the required current values;
- affected services successfully authenticate using the OpenBao-sourced values;
- no GitHub workflow uses `SOPS_AGE_KEY`.

Then:

- delete `terraform/secrets.*.enc.yaml`, `.sops.yaml`, `scripts/merge-sops-env.sh`, `scripts/check-required-sops-keys.sh`, the SOPS code path in the wrappers, and the `SECRETS_BACKEND=sops` flag;
- delete the `SOPS_AGE_KEY` GitHub secret;
- keep the SOPS-file freeze hook until the files are gone, then remove it;
- update `CLAUDE.md` and `docs/reference/secrets-management.md` so that neither describes SOPS as current.

The age key itself is kept, but only as the encryption key for the bootstrap kit (§9.1).

After this point, Git history will still contain historical encrypted SOPS files.

That is acceptable for the immediate architecture because they are no longer authoritative and cannot overwrite current OpenBao values.

Repository history rewriting is not required by this design.

---

# 26. Secret Rotation

Secret rotation becomes an explicit operation.

Conceptually:

```text
operator
    │
    ▼
authenticate to OpenBao
    │
    ▼
write new secret value (KV v2 creates a new version; the previous one stays retrievable)
    │
    ▼
update/restart consuming service as required
```

Git is not involved in storing the new value.

Undoing a bad rotation is `bao kv rollback -version=<n>` on the entry, which is itself an explicit and audited write.

Where a service's rotation currently happens by editing SOPS (for example, the Graylog `GRAYLOG_ROOT_PASSWORD` and `_SHA2` pair), the runbook is rewritten to write both fields to the entry in one KV put.

If the rotated secret is also in the bootstrap kit (§9.1), the kit is regenerated as part of the same runbook.

If configuration must change because the **name or location** of the secret changes, that reference can be committed to Git separately.

A branch checkout can therefore change:

```text
which secret path configuration refers to
```

but cannot restore an earlier value into the authoritative secret store.

---

# 27. Backup and Recovery

OpenBao Raft snapshots will form the primary secrets database backup.

OpenBao provides Raft snapshot commands for Integrated Storage.

The backup model consists of:

```text
1. Raft snapshot
2. corresponding static seal-key generation
3. documented restore procedure
```

Snapshots and seal keys must not be stored together as a single uncontrolled backup artifact.

Snapshots are taken on a schedule (the frequency is fixed in the plan) and copied off `pve`. A snapshot is useless without the seal key, so it can go to ordinary backup storage.

---

## 27.1 Recovery test

A backup is not considered valid merely because a snapshot exists.

A recovery test must demonstrate:

```text
new OpenBao LXC built using only the bootstrap kit (§9.1) — not OpenBao-held secrets
        │
        ▼
supply appropriate seal key (from the offline copy, USB B)
        │
        ▼
restore Raft snapshot
        │
        ▼
OpenBao becomes healthy
        │
        ▼
known test secret is readable
```

This should be tested before the SOPS files cease to be operational fallback data.

---

# 28. Availability Behaviour

OpenBao becomes an infrastructure dependency for workloads that retrieve secrets dynamically.

The consequences depend on the integration mechanism.

A service that already has its credentials loaded may continue functioning while OpenBao is unavailable.

A service requiring a secret during startup may not be able to start until OpenBao is available.

For the deploy-time injection model used by almost every stack today, running stacks keep their rendered configuration on their own LXC and restart without OpenBao. What an OpenBao outage blocks is **deploys and CI**, not running services. That is the main reason the USB seal key stays inserted (§8): a `pve` reboot then brings OpenBao back unattended.

Workloads moved to the OpenBao Agent `/run/secrets` pattern (§15.2) lose that property. Their secrets live in tmpfs and must be fetched again after every restart, so each such move must weigh that tradeoff.

OpenBao runs on `pve`. Deploys to other nodes (such as `pve-tiny`) therefore also depend on `pve` being up. This is a new cross-node dependency, and it is accepted.

This is acceptable for the initial homelab design.

High availability can be added later using additional Raft members if availability requirements justify it. OpenBao's Integrated Storage supports replication between Raft members.

HA is not necessary to solve the current branch-coupling problem.

---

# 29. Security Boundaries

The design makes the following explicit assumptions.

## Trusted

- Proxmox root;
- OpenBao LXC root;
- authorised OpenBao administrators;
- physical custody of seal-key media, including physical security of `pve` itself, since the operational key stays attached to it;
- the operator workstation account. It holds the deploy AppRole credentials, just as it holds the age key today, and any agent running as that account can read what those roles can read.
- Authentik administrators.

## Not trusted to mutate secrets

- Git branches;
- Terraform runs under ordinary deployment credentials;
- Ansible deployment operations;
- Docker Compose deployment;
- application source repositories;
- routine CI/deployment workflows;
- coding agents running as the operator (they get read-only deploy identities only; §13.1).

## Compromise consequences

### Git repository compromise

Attacker obtains:

- secret paths;
- policies/configuration;
- infrastructure information.

Attacker does **not** automatically obtain the current secret values.

### OpenBao data theft without seal key

Attacker obtains encrypted OpenBao data but not the independent seal key.

### Seal-key USB theft

If only the USB is taken, the seal key must be considered compromised.

If the `pve` host is taken with the USB attached, the thief has both the data and the seal key. Every secret must then be treated as exposed and rotated. This is the accepted cost of unattended unseal (§8.1).

The seal key should therefore be rotated and recovery media updated.

### Workstation compromise

The attacker obtains the deploy AppRole credentials, and so read access to every secret those roles can read. They cannot write, because write access requires an interactive OIDC login. The exposure is the same as a stolen age key today, minus write access. Recovery is to rotate the SecretIDs, then rotate the exposed secrets.

### Proxmox root compromise

The OpenBao trust boundary is effectively compromised.

This is accepted because Proxmox root already has sufficient control over workloads to compromise the environment through other means.

---

# 30. Explicit Non-Goals

The first implementation does not attempt to solve:

- full OpenBao HA;
- cloud KMS integration;
- TPM/HSM-backed sealing;
- automated credential rotation for every application;
- OpenBao dynamic database credentials;
- OpenBao PKI;
- replacement of Authentik;
- redesign of all application authentication;
- conversion of every container to an OpenBao-aware workload;
- repository-history rewriting;
- replacement of otherwise working Terraform/Ansible structures;
- secrets in Terraform state. `terraform/lxc` uses `backend = "local"`, and its state already holds values such as the LXC root password in plaintext. Moving secret *sources* to OpenBao does not change that, and it is out of scope here;
- secrets rendered into `.env` files on target LXCs by deploy-time injection. This is unchanged from today.

Those can be separate projects if a later requirement justifies them.

---

# 31. Acceptance Criteria

The migration is complete when all of the following are true.

### Secret authority

No currently used secret value is authoritative in a Git-tracked SOPS file.

### Branch independence

The following operations cannot modify existing OpenBao secret values:

```text
git checkout
git switch
git merge
git rebase
git reset
```

### Deployment isolation

Ordinary deployment identities cannot overwrite or delete secrets.

### Host isolation

A deploy identity for one environment cannot read another Proxmox node's host scope. In particular, `deploy-dev` cannot read any production node's scope.

### Service isolation

Where service-level identities have been implemented, they can retrieve only the required service/host/shared paths.

### Authentik independence of deploys

`with-secrets` / `with-secrets-prod*` work while Authentik is stopped.

### Human authentication

OpenBao UI access works using Authentik OIDC. Human write tokens are not persisted to the default token file.

### CI

CI retrieves secrets through GitHub OIDC JWT auth. No `SOPS_AGE_KEY` or other long-lived OpenBao credential is stored in GitHub.

### Break-glass recovery

OpenBao remains administrable if Authentik is unavailable: `generate-root` from the recovery keys has been exercised, and no standing root token exists.

### Seal operation

OpenBao can be unsealed using the USB-held static seal key without requiring:

- cloud KMS;
- a second OpenBao instance;
- stored Shamir shares;
- Git-held key material.

OpenBao unseals unattended after a `pve` reboot, and the seal key is absent from `vzdump` backups of the OpenBao LXC.

### Fail-closed

`with-secrets` refuses to run when any manifest entry is missing or contains an empty field.

### Backup

A Raft snapshot, the offline seal-key copy and the bootstrap kit have been used together to rebuild OpenBao on a fresh LXC. That rebuild used no secrets held in OpenBao.

### Existing workflows

Existing `with-secrets` / `with-secrets-prod*` workflows continue functioning against OpenBao during the migration unless intentionally replaced for a specific consumer.

---

# 32. Resulting Architecture

The final relationship is:

```text
                         Git
                          │
                          │ configuration +
                          │ secret references
                          ▼
        workstation with-secrets / CI runner
                          │
                          │ AppRole / JWT, read-only
                          ▼
                    ┌───────────┐
                    │ OpenBao   │
                    │           │
                    │ current   │
                    │ secret    │
                    │ values    │
                    └─────┬─────┘
                          │
                          │ values into the deploy process
                          ▼
            terraform / ansible / compose push
                          │
              ┌───────────┼────────────┐
              ▼           ▼            ▼
             pve       pve-tiny    pve-test-vm …
```

Human administration is:

```text
operator
   │
   ▼
Authentik
   │ OIDC
   ▼
OpenBao
```

OpenBao bootstrap is:

```text
USB static seal key (attached to pve, bind-mounted read-only)
        │
        ▼
OpenBao startup (unattended)
        │
        ▼
unsealed OpenBao
```

OpenBao recovery is:

```text
bootstrap kit + USB B (offline seal key) + Raft snapshot
        │
        ▼
rebuilt OpenBao
```

Git no longer sits in the secret-value lifecycle.

---

# 33. Final Design Decision

OpenBao will replace Git-tracked SOPS files as the authoritative secrets store.

A dedicated OpenBao LXC with Integrated Raft storage will provide central secrets management for the Proxmox environment.

The current distinction between common and per-Proxmox secrets will be retained semantically through `shared`, `service`, and `host` secret scopes rather than through separate encrypted YAML files.

Secrets are stored in KV v2, with one entry per service or host and field names equal to the existing environment variable names.

OpenBao's native static auto-unseal mechanism will be used with a 32-byte seal key on USB media. The USB stays attached to `pve`, so unseal is unattended, and it is bind-mounted read-only so the key never enters OpenBao's data or its backups. An offline copy and a bootstrap kit make OpenBao rebuildable without itself.

Human management (the UI and secret writes) will authenticate through Authentik using OIDC, with recovery keys and `generate-root` as break-glass.

Deploy-time reads use a read-only AppRole per environment, held on the workstation and independent of Authentik. CI uses GitHub OIDC JWT auth. Workloads may later get narrower per-service identities to retrieve their own secrets.

The existing `with-secrets` family remains as a compatibility layer, changing only its backing store, and it fails closed on missing or empty values. The switch happens as a single reconciled cutover, with the SOPS files frozen from that point. Individual applications can subsequently move to direct OpenBao access without making that conversion a prerequisite for the migration.

Most importantly:

> **Secret values cease to be Git state.**

Once a secret is written to OpenBao, a branch checkout, merge, rebase, or rollback cannot revert it. Secret changes become explicit operations against the secrets authority rather than accidental side effects of source-control operations.
