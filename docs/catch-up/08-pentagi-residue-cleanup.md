# 08 — PentAGI residue cleanup

**When:** this week, **before plan 07** (its dead scrape targets would page
as soon as alerting goes live) · **Effort:** 1–1.5 h · **Value:** Medium
**Approval names:** `catchup-08a-pentagi-firewall`, `catchup-08b-pentagi-edge`,
`catchup-08c-monitoring-targets`

## State on 2026-09-28 (verified)

PentAGI was deprecated 2026-09-06 (`docs/pentagi-stack/README.md`). Both CTs
are **already gone** from `pve`: `/nodes/pve/lxc/70010` and `/70013` return
"Configuration file … does not exist". Still around:

| Residue | Where | Live effect today |
|---|---|---|
| MikroTik rules `*42`, `*3E`, `*41`, `*5B`, `*5C`, `*5D` | router | Holes toward/from a host that no longer exists (`*5C`/`*5D` let all of `pentest_seg` reach SearXNG and cve-mcp) |
| MikroTik rules `*3F` (pentest_seg → mgmt tcp/514) and `*40` (pentest_seg → mgmt tcp/443) | router | **Still needed by greenbone-stack** (70.11: its rsyslog → Graylog, and step-ca cert issuance). Keep, but re-comment. |
| Edge route `pentagi.lab.gibbsgreatly.xyz` | Traefik + Authentik app/provider + Technitium A record | Answers `302` to Authentik, then a dead backend |
| 3 scrape targets (node_exporter `:9100`, cAdvisor `:8080`, pgexporter job `:9187`) | `deploy-monitoring-stack.yml` | Permanently `up=0` |
| Terraform state saying CT 70010 exists | `terraform/lxc/environments/pve/pentagi-stack/` (+ `pentagi-upstream-control`) | A future `terragrunt plan` would want to recreate it |
| IaC that would recreate or re-open it | `stacks/pentagi-*`, `deploy-pentagi-*.yml`, `mikrotik-firewall-pentagi-*.yml` | None until someone runs them |
| OpenBao entry `services/pentagi` | manifest + all 5 node profiles | Loaded into every deploy for no reason |
| SSH key `pentagi-test-harness` | `framework.gibbsgreatly.xyz` `~steve/.ssh/authorized_keys` | Grants a key that lived on a destroyed CT; remove anyway |

Deliberately **left alone** (separate decisions, listed in plan 13): the
Harbor project `pentagi` and its CVE allowlist (deleting the project deletes
images); greenbone's `GREENBONE_PENTAGI_PASSWORD` GVM bridge user (greenbone's
playbook requires it); `pve-test-vm`'s own PentAGI copy (that VM is stopped);
the `pentest_seg` zone itself (greenbone lives there); `docs/pentagi-stack/`
(historical record).

## Part A — firewall (operator, approval `catchup-08a-pentagi-firewall`)

Preflight: target the MikroTik; mutating; removes six rules by comment and
re-comments two; out of scope: every other rule and the zone's default-deny.

Read-only first. Confirm each rule's match criteria still matches the
2026-09-28 snapshot:

```
/ip firewall filter print detail where comment~"pentagi" or comment~"Metasploitable2"
```

Then remove (by exact comment, so IDs that changed since don't matter):

```
/ip firewall filter remove [find where comment="Metasploitable2 reverse-shell callback to pentagi-stack (host network mode)"]
/ip firewall filter remove [find where comment="mgmt_seg (monitoring-stack) to pentagi-stack pgexporter"]
/ip firewall filter remove [find where comment="mgmt_seg (monitoring-stack) to pentagi-stack cAdvisor"]
/ip firewall filter remove [find where comment="pentagi-stack: pentest_seg to ai-services-stack searxng 8082"]
/ip firewall filter remove [find where comment="pentagi-stack: pentest_seg to mcp-utility-stack cve-mcp-server 8000"]
/ip firewall filter set [find where comment="pentagi-stack rsyslog forwarding to Graylog"] comment="pentest_seg rsyslog forwarding to Graylog (greenbone-stack)"
/ip firewall filter set [find where comment="pentagi-stack node_exporter TLS cert issuance from step-ca"] comment="pentest_seg TLS cert issuance from step-ca (greenbone-stack)"
/ip firewall filter print count-only where comment~"pentagi"
```

The searxng comment matches two rules (`*5B` for the old pve-test-vm address
`.111`, `*5C` for `.11`). `remove [find …]` removes both. The final count
must print `0`.

Verify greenbone is unaffected: its logs keep arriving in Graylog (search
`source:greenbone*` for the last 15 minutes after the change), and
`https://gvm.lab.gibbsgreatly.xyz/` still answers.

## Part B — edge route (operator, approval `catchup-08b-pentagi-edge`)

The edge reconciler never deletes Authentik objects ("delete actions are
reported only and never applied", `reconcile-authentik-edge.py`), so the
Authentik side is manual:

1. Authentik admin → Applications → find the application whose slug starts
   `edge-pentagi-stack-` → Delete. Then Providers → the matching
   `edge-pentagi-stack-…` proxy provider → Delete. If the embedded outpost
   lists it, it drops off automatically.
2. After step `catchup-08-remove-iac` (below) is merged, re-render and push
   the edge config, the same two publish steps every edge change needs
   (`docs/deep-research/plan.md` records why `reconcile-edge.py --apply`
   alone isn't enough):

```bash
TASK_APPROVAL=catchup-08b-pentagi-edge ./with-secrets-prod python3 terraform/lxc/reconcile-edge.py --apply
TASK_APPROVAL=catchup-08b-pentagi-edge ./with-secrets-prod ansible-playbook -i terraform/lxc/environments/pve/proxy-stack/inventory.yml -u root terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml -e traefik_generated_source_dir=$PWD/terraform/lxc/environments/pve/.generated/traefik
TASK_APPROVAL=catchup-08b-pentagi-edge ./with-secrets-prod scripts/provision.sh --stack technitium-stack
```

3. Verify:

```bash
curl -s -m8 -o /dev/null -w '%{http_code}\n' https://pentagi.lab.gibbsgreatly.xyz/   # expect 404 (no Traefik route); 000 is also acceptable once DNS is gone
dig +short pentagi.lab.gibbsgreatly.xyz @192.168.20.15                                 # expect empty
ls terraform/lxc/environments/pve/.generated/traefik/ | grep -i pentagi                # expect nothing
```

If the route still answers `302`, the generated Traefik file for PentAGI
wasn't removed on the proxy. Find it under the proxy's dynamic-config
directory and delete that one file by hand. If DNS still answers, delete the
`pentagi` A record in Technitium's UI. Record either in the hand-back: it
means the publish path doesn't remove stale objects, which is worth its own
fix.

## Part C — repo changes

### catchup-08-monitoring-targets

```yaml
id: catchup-08-monitoring-targets
title: Remove the three PentAGI scrape targets from deploy-monitoring-stack.yml
depends_on: []

change: |
  Edit terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml and
  delete exactly these lines, nothing else:

  1. In the node_exporter job, the two lines:
                  - targets: ["{{ lookup('env', 'LAB_IP_PENTAGI') }}:9100"]
                    labels: {stack: pentagi-stack}
  2. In the cadvisor job, the two lines:
                  - targets: ["{{ lookup('env', 'LAB_IP_PENTAGI') }}:8080"]
                    labels: {stack: pentagi-stack}
  3. The whole pentagi-postgres job: the blank line before
     "            - job_name: pentagi-postgres" and the seven lines from that
     line through "                    component: pgexporter". The line
     "      notify: Restart VictoriaMetrics" that follows must stay, directly
     after the step-ca job's "                    stack: step-ca-stack".

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Removing any other target or job (coredns belongs to plan 07)"

gates:
  - id: no-pentagi
    cmd: "grep -c -i 'pentagi' terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
    expect: "prints 0"
    critical: true
  - id: diff-size
    cmd: "git diff --numstat -- terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
    expect: "0 added, 12 removed"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
```

### catchup-08-remove-iac

```yaml
id: catchup-08-remove-iac
title: Remove PentAGI IaC, manifest entry and zone membership
depends_on: []

change: |
  1. git rm these tracked files (and nothing else):
       ansible/00-initial-setup/mikrotik-firewall-pentagi-to-ai-services-searxng.yml
       ansible/00-initial-setup/mikrotik-firewall-pentagi-to-mcp-utility-cve-mcp.yml
       terraform/lxc/ansible/playbooks/deploy-pentagi-stack.yml
       terraform/lxc/ansible/playbooks/deploy-pentagi-upstream-control.yml
       terraform/lxc/ansible/playbooks/deploy-pentagi-upstream-vanilla-companion.yml
       terraform/lxc/environments/pve/pentagi-stack/terragrunt.hcl
       terraform/lxc/environments/pve/pentagi-upstream-control/terragrunt.hcl
       terraform/lxc/environments/pve-test-vm/pentagi-stack/terragrunt.hcl
       terraform/lxc/stacks/pentagi-stack/edge.yaml
       terraform/lxc/stacks/pentagi-stack/stack.yaml
       terraform/lxc/stacks/pentagi-upstream-control/stack.yaml
  2. In secrets/manifest.json: delete the whole "services/pentagi" entry line
     from "entries", and remove the string "services/pentagi" from the
     "entries" list of every profile that contains it (pve, pve-tiny,
     pve-framework, pve-test-vm, pve-test). Keep the file's formatting.
  3. In terraform/lxc/network/pve.yaml, under zones.pentest_seg.containers,
     delete exactly these two list items and keep the greenbone-stack item:
       - "pentagi-stack — ${lab_ip_pentagi}"
       - "pentagi-upstream-control (VMID 70013) — 192.168.70.13 — isolated upstream control for PentAGI model A/B testing"
  Do not touch docs/, .env*, the harbor_postconfigure role, or
  deploy-greenbone-stack.yml.

scope:
  allowed_paths:
    - ansible/00-initial-setup/
    - terraform/lxc/ansible/playbooks/
    - terraform/lxc/environments/pve/pentagi-stack/
    - terraform/lxc/environments/pve/pentagi-upstream-control/
    - terraform/lxc/environments/pve-test-vm/pentagi-stack/
    - terraform/lxc/stacks/pentagi-stack/
    - terraform/lxc/stacks/pentagi-upstream-control/
    - secrets/manifest.json
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Deleting any file not listed in change item 1"
    - "Any terragrunt, provision.sh, ssh or bao command"

gates:
  - id: files-gone
    cmd: "git ls-files | grep -E 'pentagi' | grep -vE '^docs/|cve_allowlist_pentagi' || echo none"
    expect: "prints none"
    critical: true
  - id: manifest
    cmd: >-
      python3 -c "import json;m=json.load(open('secrets/manifest.json'));assert 'services/pentagi' not in m['entries'];assert all('services/pentagi' not in p['entries'] for p in m['profiles'].values());print('ok')"
    expect: "prints ok"
    critical: true
  - id: zone
    cmd: >-
      python3 -c "import yaml;z=yaml.safe_load(open('terraform/lxc/network/pve.yaml'))['zones']['pentest_seg']['containers'];assert len(z)==1 and z[0].startswith('greenbone-stack');print('ok')"
    expect: "prints ok"
    critical: true
  - id: secrets-load
    cmd: "./with-secrets-prod printenv LAB_IP_PROXY"
    expect: "prints 192.168.30.10 (the loader still resolves the pve profile after the manifest edit)"
    critical: true
```

## Part D — operator clean-ups after the merge

1. **Local Terraform state** (untracked, only on the workstation):
   `rm -rf terraform/lxc/environments/pve/pentagi-stack terraform/lxc/environments/pve/pentagi-upstream-control`
   (the CTs don't exist; this state only describes a ghost).
2. **Monitoring** (approval `catchup-08c-monitoring-targets`):
   `TASK_APPROVAL=catchup-08c-monitoring-targets ./with-secrets-prod scripts/provision.sh --stack monitoring-stack`,
   then
   `curl -s --data-urlencode 'query=up{stack="pentagi-stack"}' http://192.168.20.12:8428/api/v1/query`
   returns an empty result within a few minutes.
3. **OpenBao entry**: after the manifest change is on `stable`, delete the
   KV entry (explicit human login):
   ```bash
   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
   bao kv metadata delete -mount=kv services/pentagi
   unset BAO_TOKEN
   ```
   The OpenBao dashboard's drift panel should show 0 afterwards.
4. **Harbor robot**: Harbor → Robot Accounts → delete the robot named in
   `PENTAGI_HARBOR_ROBOT_USER` (read it before step 3:
   `./with-secrets-prod printenv PENTAGI_HARBOR_ROBOT_USER`).
5. **Framework SSH key**:
   ```bash
   ssh steve@framework.gibbsgreatly.xyz 'grep -c "pentagi-test-harness$" ~/.ssh/authorized_keys'   # expect 1
   ssh steve@framework.gibbsgreatly.xyz "sed -i.bak-pentagi '/pentagi-test-harness\$/d' ~/.ssh/authorized_keys && grep -c pentagi-test-harness ~/.ssh/authorized_keys"   # expect 0
   ```
   Then delete the memory note `project_pentagi_harness_key_cleanup`.

## Done when

- Router: `print count-only where comment~"pentagi"` = 0; greenbone logs flow.
- `pentagi.lab.gibbsgreatly.xyz` no longer resolves or routes.
- No `pentagi-stack` series in VictoriaMetrics; `services/pentagi` gone from
  the manifest and OpenBao; the harness key is gone from Framework.
- `docs/pentagi-stack/README.md`'s deprecation note gets one line: "Torn
  down 2026-MM-DD, see docs/catch-up/08."
