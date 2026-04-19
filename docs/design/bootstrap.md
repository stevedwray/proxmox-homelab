# Bootstrap Stages

## The circular dependency problem

Deploying a secure container platform requires services that cannot yet exist when deployment
begins. Harbor enforces image vulnerability policy, but must itself be deployed before that
policy can be enforced. A CI runner gates deployments through automated checks, but must be
deployed before gate checks can run. Each of these services depends on the platform being
stable — yet the platform cannot become stable without them.

This is the same problem faced by any self-hosting compilation system: to build the
compiler, you need a compiler. The solution, as with Linux From Scratch, is a temporary
minimal environment that exists only to produce the permanent environment, then is
discarded. The temporary environment does not embody the target security posture — it is a
bridge. Security controls are tightened at each transition and the bridge itself is torn
down once the crossing is complete.

This document defines deployment stages. Stage 0 is a workstation-only prerequisite.
Stage 1 is the temporary bridge. Stage 2 is the permanent platform foundation. Stage 3a
brings up the edge foundation that other browser-facing services depend on. Stage 3b and
beyond build on that foundation with full security controls active from the outset.

---

## Stage 0 — Workstation bootstrap

### Purpose

Prepare the operator's workstation to run infrastructure commands against a Proxmox host.
No Proxmox host is required. No containers are deployed. The output of Stage 0 is a
workstation that can execute `./with-secrets terragrunt apply` and
`./with-secrets ansible-playbook` without credential errors.

### What runs

Nothing runs on Proxmox during Stage 0. All work is on the operator's local machine:

- Retrieve the age private key from Bitwarden (`proxmox-homelab age private key`) and
  install it at `~/.config/sops/age/keys.txt` with mode `0600`
- Verify `sops --decrypt terraform/secrets.enc.yaml` succeeds
- Confirm the `with-secrets` wrapper exists at the repository root and is executable

### Secrets posture

Stage 0 is where the `with-secrets` migration (Phase 03d) lives. From Stage 0 onwards,
there is no `.env` file and no `sync-secrets.sh`. The age private key at
`~/.config/sops/age/keys.txt` is the only credential that needs to exist on the
workstation. `with-secrets` handles all further secret delivery by decrypting
`terraform/secrets.enc.yaml` in memory via `sops exec-env`. The decrypted values are
injected into the subprocess environment only and are never written to disk.

This design is consistent with ADR-06 (secrets runtime delivery via SOPS) and directly
addresses TM-02 and TM-03 from the threat model: the `.env` file is never written, and the
Bitwarden session token is not used during routine operations. It supersedes the SEC-03
constraint, which required ephemeral manual deletion of the `.env` file — a procedural
control that `with-secrets` makes unnecessary by eliminating the file entirely.

### Entry condition

- A workstation with `git`, `sops`, `tofu`/`terragrunt`, `ansible-playbook`, and `age`
  installed
- Access to Bitwarden to retrieve the age private key (one-time retrieval; Bitwarden is not
  needed for subsequent operations)

### Exit condition

- `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml`
  succeeds without error
- `./with-secrets echo OK` exits 0
- Phase 03d (Secrets Delivery Hardening) is merged into `dev/pve-test`

### Where it fits in the plan

Stage 0 maps to Phase 03d. Phase 03d is a workstation and repository tooling task. It
requires no deployed service and no deployment phase to be complete. It should be done once,
merged, and from that point the `.env` approach no longer exists anywhere in the repository.
All subsequent stages and all subsequent phases use `with-secrets` as the sole secret
delivery mechanism.

---

## Stage 1 — Temporary bootstrap containers

### Purpose

Deploy a minimal, explicitly temporary set of containers whose only purpose is to produce
the environment Stage 2 requires. Stage 1 containers are not the final state. They will be
torn down once Stage 2 is confirmed healthy.

The target security posture requires Harbor as the image source for all subsequent
deployments. Harbor cannot provide images for its own initial deployment. Stage 1 breaks
this loop: Harbor is deployed in Stage 1 pulling from Docker Hub, used to seed all Stage 2
and Phase 04 images, and then replaced by the Stage 2 permanent Harbor instance. The CI
runner is deployed in Stage 1 to validate that GitHub Actions pipelines succeed before the
permanent runner takes its place. Portainer provides container inspection visibility
throughout the bootstrap.

### What runs

| Service | VMID | Zone | IP |
|---|---|---|---|
| Portainer (temporary) | 120 | `mgmt_seg` | `10.57.1.20` |
| Harbor (temporary) | 121 | `infra_seg` | `10.57.3.10` |
| CI runner (temporary) | 141 | `build_seg` | `10.57.0.63` |

All Stage 1 containers pull their images directly from Docker Hub. This is the only phase
in which Docker Hub direct pulls are permitted at deployment time. Harbor's proxy cache
projects are configured immediately after the Harbor LXC is healthy, enabling the
pre-seeding step. The CI runner registers with GitHub Actions using a repository-scoped
registration token stored in `terraform/secrets.enc.yaml`.

The critical Stage 1 deliverable is Harbor being pre-seeded with all images that Stage 2
and Phase 04 will need. This pre-seeding step is the handoff between Stage 1 and Stage 2:
once the required images are in Harbor, Stage 2 deployments are isolated from Docker Hub
entirely.

### Secrets posture

`with-secrets` is used from Stage 0 onwards. There is no point at which `.env` is needed.
The temporary nature of Stage 1 containers does not change how secrets are delivered on the
operator workstation — the operator runs `./with-secrets terragrunt apply` for Stage 1
deployments in exactly the same way as Stage 2. Harbor robot account authentication (SEC-06)
is configured in Stage 1 but not yet enforced as an image pull requirement — Stage 1
containers pull from Docker Hub directly rather than via robot account.

### Entry condition

- Stage 0 complete — `with-secrets` works and the age key is on the workstation
- Proxmox host is running and accessible
- SDN VLAN zones (`mgmt_seg`, `infra_seg`, `build_seg`) are applied to `pve-test`
- `terraform/secrets.enc.yaml` contains real values for all Proxmox API credentials

### Exit condition

- Harbor is running at `10.57.3.10` with all Stage 2 and Phase 04 required images
  pre-pulled and available in the proxy cache
- CI runner is registered with GitHub Actions and at least one pipeline run has succeeded
- Portainer is accessible at `10.57.1.20` for container inspection

---

## Stage 2 — Production deployment

### Purpose

Deploy the permanent versions of Portainer, Harbor, and CI runner using Stage 1
infrastructure. Stage 1 containers are torn down after Stage 2 containers are confirmed
healthy. After Stage 2, the platform has the foundation required for Phase 04.

### What runs

| Service | VMID | Zone | IP |
|---|---|---|---|
| Portainer (permanent) | 120 | `mgmt_seg` | `10.57.1.20` |
| Harbor (permanent) | 121 | `infra_seg` | `10.57.3.10` |
| CI runner (permanent) | 141 | `build_seg` | `10.57.0.63` |

Stage 2 uses the same VMIDs as Stage 1. The transition is an in-place replacement:
`terragrunt destroy` of the Stage 1 stack followed by `terragrunt apply` of the Stage 2
stack at the same VMID. NetBox records the transition. Stage 1 Harbor remains running until
Stage 2 Portainer and CI runner are deployed and confirmed healthy, at which point Stage 1
Harbor is replaced by Stage 2 Harbor.

The recommended deployment order is Portainer first (Stage 1 Harbor remains available),
then CI runner, then Harbor last. The Harbor replacement carries brief downtime: Stage 1
Harbor is destroyed and Stage 2 Harbor is provisioned at VMID 121 in sequence. Stage 2
Harbor bootstraps its component images from Docker Hub on first boot, paralleling the Stage
1 approach. Once Stage 2 Harbor is healthy, it becomes the sole image source for all
subsequent deployments.

Design note: Harbor's own component images should be included in the Stage 1 pre-seeding
step under a dedicated `harbor` project, so Stage 2 Harbor can pull its own images from
Stage 1 Harbor during the brief window before Stage 1 Harbor is destroyed. If the timing
makes this impractical, Stage 2 Harbor falls back to a direct Docker Hub bootstrap as
described above. Revisit if a data migration or snapshot-based approach is later required.

### Secrets posture

All secrets delivered via `with-secrets` as in Stage 1. Stage 2 adds robot account
authentication for Harbor image pulls (SEC-06): Ansible playbooks reference images at
`10.57.3.10/...` and authenticate as `robot$ci-runner`. No anonymous image pulls are
permitted once Stage 2 is complete.

### Entry condition

- Stage 1 complete — Harbor is running with all Stage 2 images available, CI runner is
  registered and has validated at least one pipeline run
- Robot account credentials (`HARBOR_ROBOT_USER`, `HARBOR_ROBOT_PASSWORD`) are stored in
  `terraform/secrets.enc.yaml`

### Exit condition

- Permanent Portainer, Harbor, and CI runner are running at their assigned VMIDs
- Stage 1 temporary containers are torn down and confirmed absent
- All subsequent container deployments reference Harbor at `10.57.3.10` as the image source
- Phase 04 prerequisites can be satisfied

---

## Stage 3a — Edge foundation

### Purpose

Bring up the DNS, ingress, certificate, and identity services that stack-owned
browser provisioning depends on. This stage resolves the bootstrap problem for
the edge reconciler: manifests cannot be applied until CoreDNS, Traefik, and
Authentik API access exist.

### Deployment order

Stage 3a order is load-bearing in Mode 2:

1. **CoreDNS** (`dns-stack`, VMID 151, `10.57.1.13`) with a seed
   `lab.gibbsgreatly.xyz` zone. The seed zone contains only bootstrap and
   non-browser records required before generated browser records exist.
2. **Traefik** (`proxy-stack`, VMID 153, `10.57.2.10`) with static runtime
   configuration: entrypoints, providers, certificate resolvers, default store,
   and shared middleware definitions. Per-service browser routes are not
   considered stack-owned until the edge reconciler publishes generated files.
3. **step-ca** (`step-ca-stack`, VMID 152, `10.57.1.11`). ACME challenge paths
   that depend on Traefik are validated only after Traefik and the required
   MikroTik policy are in place.
4. **Authentik** (`authentik-stack`, VMID 150, `10.57.1.10`) via direct IP
   first boot. The operator completes first setup and stores the automation API
   token in SOPS before Authentik reconciliation is allowed.

### Edge reconciler activation

The stack-owned edge reconciler is disabled during Stage 3a until:

- CoreDNS answers authoritative queries for `lab.gibbsgreatly.xyz`
- MikroTik conditionally forwards `lab.gibbsgreatly.xyz` to CoreDNS
- Traefik is running and can load file-provider dynamic config
- Authentik is healthy and an API token is available for routes that need
  Authentik objects

Terraform does not detect this state and does not perform a hidden second pass.
The operator runs the explicit edge reconciler after Stage 3a exits.

### Exit condition

- CoreDNS, Traefik, step-ca, and Authentik are deployed on pve-test.
- Authentik direct first boot is complete and the automation API token is stored.
- Edge reconciliation can run in dry-run mode and report planned DNS, Traefik,
  and Authentik changes.

---

## Stage 3b — Full platform (Phase 04 and later)

### Purpose

Deploy all remaining shared services and application stacks on the Stage 2 and Stage 3a
foundation. Stage 3b maps to Phase 04 and later in the execution plan after the edge
foundation exists. Harbor-sourced images, robot account authentication, `with-secrets`, and
explicit edge reconciliation apply to every deployment from this point.

CI-gated deployments also become active in Stage 3b: the permanent CI runner (Stage 2) gates
Phase 05 supply chain jobs (Trivy scan, Syft SBOM, Cosign signing) that must pass before
image promotion in Harbor. This is the final security control not yet present in Stage 2.

---

## Security controls by stage

| Control | Stage 0 | Stage 1 | Stage 2 | Stage 3a+ |
|---|---|---|---|---|
| `with-secrets` for operator secret delivery | Yes | Yes | Yes | Yes |
| Harbor as image source | N/A | No | Yes | Yes |
| Robot account authentication for image pulls | N/A | No | Yes | Yes |
| Harbor vulnerability policy gate | N/A | No | Yes | Yes |
| CI-gated deployments | No | No | No | Yes |
| `.env` file on workstation | No | No | No | No |

`with-secrets` is active from Stage 0 because Stage 0 is where Phase 03d is executed and
merged. There is no `.env` fallback at any stage.

Harbor is not the image source in Stage 1 because Harbor does not yet exist at the start of
Stage 1. Stage 1 is the exception that produces the rule: after Stage 1, Harbor is the
mandatory source for all image pulls.

---

## Mapping to the execution plan

| Stage | Execution plan | Scope |
|---|---|---|
| Stage 0 | Phase 03d | Workstation and repository tooling only |
| Stage 1 | Phase 00c Part A | Proxmox — temporary bootstrap containers |
| Stage 2 | Phase 00c Part B | Proxmox — permanent container replacement |
| Stage 3a | Phase 04 edge foundation | CoreDNS, Traefik, step-ca, Authentik first boot |
| Stage 3b+ | Phase 04 and later | Full platform and application stacks |

Phase 00c covers both Stage 1 and Stage 2. Phase 03d (Stage 0) is not part of Phase 00c —
it is an independent, workstation-only task that can be completed at any time before first
deployment.

See [docs/plan/phase-00c-bootstrap-sequence.md](../plan/phase-00c-bootstrap-sequence.md)
for the execution plan for Stage 1 and Stage 2.

See [docs/plan/phase-03d-secrets-hardening.md](../plan/phase-03d-secrets-hardening.md)
for Phase 03d (Stage 0).

---

## Two modes of work

The repository is used in two fundamentally different modes. Confusing them is the most
common source of incorrect planning decisions.

**Mode 1 — Development:** Building and refining the playbook. Writing Ansible roles,
exploring how services are configured, generating code and documentation, understanding
what a given service's configuration looks like in practice. Order of work does not matter
in Mode 1. A service can be stood up temporarily on any machine, for any purpose, and then
discarded. The phase sequence and bootstrap stages do not constrain Mode 1 work. You can
deploy Harbor before Portainer, explore Authentik before deploying a CI runner, or run
Phase 04 playbooks to understand them without having completed Phase 00c. None of this
violates the model — Mode 1 is exploration, and exploration has no required order.

**Mode 2 — Deployment:** Executing the playbook on real infrastructure to produce a
running, correct system. Order is load-bearing. The bootstrap stage model, phase gates, and
task prerequisites all describe Mode 2. A pve-test wipe-and-rebuild is a Mode 2 activity.
The phase sequence exists to ensure Mode 2 deployments succeed reliably and without
circular dependency failures.

The phase documents and task documents describe Mode 2 deployment ordering. The stage
sequence and phase gate requirements in this document also describe Mode 2. The design
documents (GreenField.md, architecture.md) describe the target architecture that Mode 2
produces. None of these constrain Mode 1.

When reading a phase document and finding that a prerequisite has not been met, the
appropriate question is: "Am I doing Mode 2 (deployment) work right now?" If not, proceed
with Mode 1 exploration in whatever order is useful. If yes, satisfy the prerequisites
before proceeding.
