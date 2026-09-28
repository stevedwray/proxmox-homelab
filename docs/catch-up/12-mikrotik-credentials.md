# 12 — MikroTik credential standardisation

**When:** following weeks · **Effort:** 45 min · **Value:** Low-Med
**Production access:** none for the repo change; one read-only playbook run
to verify

## What's actually wrong (verified 2026-09-28)

The "MIKROTIK_USER lacks write permission" gap (`docs/gaming-stack-lab/README.md`)
is real, but mostly already worked around. 17 of the 22
`ansible/00-initial-setup/mikrotik-*.yml` playbooks use the admin credential
first:

```text
mikrotik_user: >-
  {{ lookup('env', 'MIKROTIK_ADMIN') | default(lookup('env', 'MIKROTIK_USER'), true) ... }}
mikrotik_password: >-
  {{ lookup('env', 'MIKROTIK_ADMIN_PASSWORD') | default(lookup('env', 'MIKROTIK_PASSWORD'), true) }}
```

`MIKROTIK_ADMIN`/`MIKROTIK_ADMIN_PASSWORD` are in OpenBao `services/mikrotik`,
loaded by every production profile. Five older playbooks read only
`MIKROTIK_USER`/`MIKROTIK_PASSWORD`, so their writes fail with "not enough
permissions (9)":

- `mikrotik-build-seg-data-plane-reconcile.yml`
- `mikrotik-build-seg-vlan10-reconcile.yml`
- `mikrotik-firewall-greenbone-lan-scan-reach.yml`
- `mikrotik-firewall-greenbone-router-ssh-input.yml`
- `mikrotik-firewall-media-seg-wireguard-egress.yml`

**Decision taken in this plan:** standardise those five on the same
admin-first fallback rather than widen `MIKROTIK_USER`'s RouterOS
permissions. That matches what the other 17 already do and needs no router
change. `MIKROTIK_USER` stays the limited API user for read paths.

## Step

### catchup-12-admin-fallback

```yaml
id: catchup-12-admin-fallback
title: Use the admin-first MikroTik credential fallback in the last five playbooks
depends_on: []

change: |
  In each of these five files:
    ansible/00-initial-setup/mikrotik-build-seg-data-plane-reconcile.yml
    ansible/00-initial-setup/mikrotik-build-seg-vlan10-reconcile.yml
    ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml
    ansible/00-initial-setup/mikrotik-firewall-greenbone-router-ssh-input.yml
    ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml
  replace the play-level var definitions of mikrotik_user and
  mikrotik_password (each currently a single line of the form
  `mikrotik_user: "{{ lookup('env', 'MIKROTIK_USER') }}"` and
  `mikrotik_password: "{{ lookup('env', 'MIKROTIK_PASSWORD') }}"`, possibly
  with a `| default(...)` suffix) with this LITERAL block, at the same
  indentation as the lines it replaces:

    mikrotik_user: >-
      {{
        lookup('env', 'MIKROTIK_ADMIN')
        | default(lookup('env', 'MIKROTIK_USER'), true)
      }}
    mikrotik_password: >-
      {{
        lookup('env', 'MIKROTIK_ADMIN_PASSWORD')
        | default(lookup('env', 'MIKROTIK_PASSWORD'), true)
      }}

  If a file's existing definition differs from that form in a way that
  isn't a plain env lookup (e.g. it reads a different variable), stop and
  hand back instead of editing that file. Change nothing else in any file.

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-build-seg-data-plane-reconcile.yml
    - ansible/00-initial-setup/mikrotik-build-seg-vlan10-reconcile.yml
    - ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml
    - ansible/00-initial-setup/mikrotik-firewall-greenbone-router-ssh-input.yml
    - ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running any playbook"

gates:
  - id: all-admin-first
    cmd: "git grep -L 'MIKROTIK_ADMIN' -- 'ansible/00-initial-setup/mikrotik-*.yml' || true"
    expect: "prints nothing (every MikroTik playbook now references the admin credential)"
    critical: true
  - id: syntax
    cmd: "cd ansible && for f in mikrotik-build-seg-data-plane-reconcile mikrotik-build-seg-vlan10-reconcile mikrotik-firewall-greenbone-lan-scan-reach mikrotik-firewall-greenbone-router-ssh-input mikrotik-firewall-media-seg-wireguard-egress; do ansible-playbook --syntax-check 00-initial-setup/$f.yml || exit 1; done"
    expect: "exit 0"
    critical: true
  - id: lint
    cmd: "cd ansible && ansible-lint 00-initial-setup/*.yml"
    expect: "0 failure(s)"
    critical: true
```

## Operator: verify one playbook end to end (idempotent, no change expected)

```bash
./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml
```

Expect `changed=0 failed=0`. The rule exists and the play only re-reads and
asserts. Write-capable credentials are now in use, even though nothing
needed writing.

## Done when

- Every `mikrotik-*.yml` references `MIKROTIK_ADMIN`.
- Gap (3) in `docs/gaming-stack-lab/README.md` is closed with a one-line note
  pointing here, and the `MIKROTIK_USER` "lacks write" wording in plan 01's
  playbook header can stay (it explains why the fallback exists).
