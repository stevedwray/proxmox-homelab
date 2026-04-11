# 03-code-quality-02 — SSL/TLS acknowledgement in proxmox_client.py (issue #35)

## Status

PENDING

## Phase

Phase 03 — Code Quality and Bug Fixes

## Prerequisites

- Phase 00 complete — branch is clean
- Read `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py` before making any change

## Objective

The intentional SSL certificate verification disable in `proxmox_client.py` is explained by an inline comment, the SonarCloud findings (`python:S5527`, `python:S4423`, `python:S4830`) are acknowledged, and issue #35 is closed.

## Scope

- `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py` — add comment block near lines 44–46
- Issue #35 closed on GitHub

## Out of Scope

- Changing the SSL behavior (it is intentionally disabled — Proxmox uses self-signed certs in homelab)
- Other Python files in the integrations directory
- SonarCloud UI configuration (repo-owner decision)

## Inputs

- `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py` — read lines 40–55 to find exact SSL-disabling code
- `docs/plan/phase-03-code-quality.md` — Batch 2 for context

## Expected Outputs

- `proxmox_client.py` — comment block added above SSL-disabling code

## Constraints and Conventions

- This is an acknowledgement, not a fix. Do NOT enable certificate verification.
- The comment must explain: (1) why it's disabled, (2) that it's intentional, (3) that it's internal LAN-only
- Check whether the project uses `# NOSONAR` or `# noqa:` style suppression; use the consistent style
- Keep the comment concise (3–5 lines maximum)

## Acceptance Criteria

- [ ] `proxmox_client.py` has a comment block above the SSL-disabling code explaining the intent
- [ ] Comment references the homelab context and internal LAN-only use
- [ ] No other changes to the file
- [ ] `ansible-lint terraform/lxc/ansible/` still passes at 0 violations (not directly related but verify no regressions)
- [ ] Issue #35 closed on GitHub

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Add an explanatory comment to proxmox_client.py to acknowledge intentional SSL
certificate verification disable. This is a documentation fix, not a code logic change.

BEFORE EDITING, READ THESE FILES:
  terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py
    Focus on lines 40–55 to find the SSL-disabling code
  docs/plan/phase-03-code-quality.md   (Batch 2)

CONTEXT:
  The Proxmox API client disables SSL certificate verification because Proxmox uses a
  self-signed certificate in this homelab environment. This is intentional and acceptable
  for internal LAN-only traffic. SonarCloud flags three findings (python:S5527, python:S4423,
  python:S4830), but all three are false positives in this context.

CHANGE TO MAKE:
  Immediately above the SSL-disabling code (the lines that set verify=False, ssl=False,
  or similar), add a comment block:

  # Certificate verification is intentionally disabled for the internal Proxmox API.
  # The Proxmox node uses a self-signed certificate in this homelab environment.
  # This is acceptable for internal LAN-only traffic.
  # See docs/reference/proxmox-server-baseline.md
  # noqa: S5527, S4423, S4830

  Adjust the noqa line format to match whatever style is used elsewhere in the project.
  If no suppression style is in use, omit the noqa line and rely on the comment alone.

COMMIT:
  git add terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py
  git commit -m "fix(netbox): acknowledge intentional SSL disable in proxmox_client.py (Closes #35)

Self-signed cert in homelab — certificate verification disabled intentionally.
Suppression comments added for python:S5527, S4423, S4830."

  git push origin dev/pve-test
  gh issue close 35 --comment "Acknowledged — homelab self-signed cert. Suppression comment added."

DONE WHEN: Comment is present, issue #35 is closed, and no other lines in the file changed.
```
