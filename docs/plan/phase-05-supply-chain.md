# Phase 05 — Supply Chain Security (Trivy, Syft, Cosign)

## Goal

Implement a software supply chain security pipeline so that every container image used in the lab:

1. Has been scanned for vulnerabilities (Trivy)
2. Has a Software Bill of Materials (Syft)
3. Is cryptographically signed (Cosign)
4. Is pulled only from Harbor (never directly from Docker Hub at runtime)

This phase adds the tooling and CI pipeline stages. It does **not** yet migrate application stacks to pull from Harbor — that happens in Phase 06.

## Prerequisites

- Phase 01 (ci-runner-01) complete — self-hosted runner must be online
- **Phase 03b complete** — Harbor has Trivy scanner enabled, projects created, proxy cache configured, and robot account ready
- Phase 04 (core shared services) complete — monitoring stack running so scan results are visible in dashboards

## Related GreenField sections

- GreenField §5 (Supply chain: Harbor + signing)
- GreenField §7 (Policy-as-code: OPA/Conftest, Trivy IaC)

---

## Part A — Trivy CI image scanning (extends Phase 03b Harbor scanning)

Harbor already scans every image on push (configured in Phase 03b). This part adds a second Trivy scan gate in CI that runs against the specific image digest produced by a build job. The Harbor scan catches vulnerabilities at cache time; this CI scan catches them at build/promote time.

Trivy also currently runs in the `sast-scan` CI job on `ubuntu-latest` for filesystem, secrets, and IaC misfigurations. That job remains unchanged.

### Add Trivy image scan job to CI

When Harbor stores a newly built image (Phase 06), add a CI job to scan that specific image digest via Trivy:

```yaml
  trivy-image-scan:
    name: Trivy image scan
    runs-on: [self-hosted, pve-test, build]
    needs: [build-image]
    steps:
      - uses: actions/checkout@v4

      - name: Log in to Harbor
        run: |
          echo "$HARBOR_ROBOT_PASSWORD" | \
            docker login 10.57.3.10 -u "$HARBOR_ROBOT_USER" --password-stdin
        env:
          HARBOR_ROBOT_USER: ${{ secrets.HARBOR_ROBOT_USER }}
          HARBOR_ROBOT_PASSWORD: ${{ secrets.HARBOR_ROBOT_PASSWORD }}

      - name: Run Trivy image scan
        uses: aquasecurity/trivy-action@v0.35.0
        with:
          scan-type: image
          image-ref: "10.57.3.10/<project>/<image>:<tag>"
          format: sarif
          output: trivy-image.sarif
          severity: CRITICAL,HIGH
          exit-code: "1"         # fail CI on CRITICAL/HIGH

      - name: Upload image SARIF
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: trivy-image.sarif
```

`HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` were added as GitHub Actions secrets in Phase 03b.

---

## Part B — Syft (SBOM generation)

### Install Syft on the CI runner

Add a task to `deploy-ci-runner.yml` to install Syft:

```yaml
- name: Install Syft
  ansible.builtin.shell: |
    curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | \
      sh -s -- -b /usr/local/bin v<SYFT_VERSION>
  args:
    creates: /usr/local/bin/syft
```

Pin to a specific version (e.g., `v1.19.0`). Check [Syft releases](https://github.com/anchore/syft/releases) for the latest stable.

### Add SBOM generation to CI

Add a `generate-sbom` job after each image build:

```yaml
  generate-sbom:
    name: Generate SBOM
    runs-on: [self-hosted, pve-test, build]
    needs: [build-image]
    steps:
      - name: Generate SBOM (SPDX)
        run: |
          syft 10.57.3.10/<project>/<image>:<tag> \
            --output spdx-json=sbom.spdx.json

      - name: Upload SBOM as artifact
        uses: actions/upload-artifact@v4
        with:
          name: sbom-${{ github.sha }}
          path: sbom.spdx.json
          retention-days: 90
```

---

## Part C — Cosign (image signing)

### Install Cosign on the CI runner

Add to `deploy-ci-runner.yml`:

```yaml
- name: Install Cosign
  ansible.builtin.shell: |
    curl -sSfL "https://github.com/sigstore/cosign/releases/download/v<VERSION>/cosign-linux-amd64" \
      -o /usr/local/bin/cosign && chmod +x /usr/local/bin/cosign
  args:
    creates: /usr/local/bin/cosign
```

Pin the Cosign version.

### Generate signing keys

Generate a key pair for signing. Store the private key encrypted with a passphrase:

```bash
# On the workstation (not in CI):
cosign generate-key-pair

# This creates cosign.key (private, encrypted) and cosign.pub (public)
```

- `cosign.key` → encrypt with SOPS+age (see `terraform/secrets.enc.yaml` pattern) and commit to the repo, or store as a GitHub Actions secret
- `cosign.pub` → commit to the repo unencrypted (it is a public key)
- `COSIGN_PASSWORD` → GitHub Actions secret (passphrase protecting the private key)

**Never commit the unencrypted `cosign.key`.**

### Sign images in CI

After image build and push to Harbor:

```yaml
  sign-image:
    name: Sign image with Cosign
    runs-on: [self-hosted, pve-test, build]
    needs: [build-image, trivy-image-scan]  # only sign after scan passes
    steps:
      - uses: actions/checkout@v4

      - name: Sign image
        env:
          COSIGN_PASSWORD: ${{ secrets.COSIGN_PASSWORD }}
          COSIGN_KEY: ${{ secrets.COSIGN_KEY }}   # or read from SOPS-decrypted file
        run: |
          echo "$COSIGN_KEY" > /tmp/cosign.key
          cosign sign --key /tmp/cosign.key \
            10.57.3.10/<project>/<image>@<digest>
          rm /tmp/cosign.key
```

### Verify signatures at deploy time

In Ansible playbooks that pull images, add a pre-pull verification step:

```yaml
- name: Verify image signature
  ansible.builtin.command:
    cmd: >
      cosign verify
      --key /etc/cosign/cosign.pub
      10.57.3.10/<project>/<image>@<digest>
  changed_when: false
```

Store `cosign.pub` on each LXC under `/etc/cosign/` via the base Ansible role.

---

## Part D — Harbor-only image policy (enforcement in CI)

### Goal

Harbor proxy cache and project policies were configured in Phase 03b. This part adds a **CI enforcement check** so that any compose file accidentally referencing an upstream registry directly (rather than the Harbor proxy) fails the pipeline.

### Add a compose image reference lint check

Add a CI step (can go in `validate.yml`) that fails if any compose file references `docker.io`, `ghcr.io`, or `quay.io` directly:

```yaml
  harbor-image-policy:
    name: Enforce Harbor-only image references
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check compose files use Harbor proxy
        run: |
          # Fail if any image: line references an upstream registry directly
          if grep -r "^\s*image:.*\(docker\.io\|ghcr\.io\|quay\.io\|registry\.k8s\.io\)" \
               terraform/lxc/stacks/ --include="*.yml" --include="*.yaml"; then
            echo "ERROR: Direct upstream registry references found. Use 10.57.3.10/... instead."
            exit 1
          fi
          echo "OK — all image references use Harbor proxy."
```

Add this job to the `validate.yml` workflow alongside the existing Terraform and Ansible lint jobs.

---

## GitHub Actions secrets required

Add these to the repository (Settings → Secrets → Actions):

| Secret | Description |
|---|---|
| `HARBOR_ROBOT_USER` | Harbor robot account username for CI |
| `HARBOR_ROBOT_PASSWORD` | Harbor robot account password |
| `HARBOR_DOCKERHUB_USERNAME` | Docker Hub account used by CI source-image pulls to avoid anonymous rate limits |
| `HARBOR_DOCKERHUB_PASSWORD` | Docker Hub token/password used by CI source-image pulls to avoid anonymous rate limits |
| `COSIGN_KEY` | PEM-encoded encrypted cosign private key |
| `COSIGN_PASSWORD` | Passphrase for the cosign private key |

---

## Commit and push

```bash
git checkout -b feat/supply-chain-pipeline baseline/teardown-validated

# After all changes:
git add .github/workflows/ \
        terraform/lxc/ansible/playbooks/deploy-ci-runner.yml \
        cosign.pub

git commit -m "feat(ci): add supply chain pipeline — Trivy image scan, Syft SBOM, Cosign signing"
git push origin feat/supply-chain-pipeline
# Merge to baseline/teardown-validated via PR
```

---

## Acceptance criteria

> Harbor Trivy scanner, projects, proxy cache, and robot account are verified in Phase 03b — not repeated here.

### Trivy CI gate
- [ ] Trivy image scan CI job runs on self-hosted runner after image build
- [ ] CRITICAL/HIGH findings fail CI (exit-code: 1)
- [ ] SARIF results uploaded to GitHub Security tab

### Syft
- [ ] Syft installed on ci-runner-01 (pinned version)
- [ ] SBOM is generated for each image build as a CI artifact
- [ ] SBOM is in SPDX-JSON format

### Cosign
- [ ] `cosign.pub` committed to repo
- [ ] `cosign.key` stored as encrypted GitHub Actions secret (never committed unencrypted)
- [ ] Images are signed in CI after scan pass
- [ ] `cosign verify --key cosign.pub` passes for at least one signed image in Harbor

### Harbor-only policy (enforcement)
- [ ] All compose files for Phase 06+ stacks reference `10.57.3.10/<project>/` only
- [ ] CI check added that flags any compose file referencing `docker.io/` or `ghcr.io/` directly
- [ ] Content trust / Cosign signature verification enabled in at least one Harbor project
