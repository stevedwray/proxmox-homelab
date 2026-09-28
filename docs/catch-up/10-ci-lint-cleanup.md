# 10 — CI lint and policy cleanup

**When:** right after plan 06 (06 makes these gates run on every PR into
`stable`) · **Effort:** 2–3 h · **Value:** Medium (restores a CI signal
people can trust)
**Approval names:** `catchup-10-redeploy-<stack>` for the redeploys in Part C

## Real size (measured locally 2026-09-28, same commands as CI)

| Gate | Reported at #434 | Actually failing |
|---|---|---|
| ansible-lint | "193" | **21 failures.** The other 172 are warn-list (`yaml[line-length]`, `var-naming[no-role-prefix]`) and don't fail the job |
| Harbor-only image refs | 13 | 13 (6 in cse-* compose files, 1 in cse-kali, 3 in pterodactyl-lab compose, 3 in `stack-request.yaml`, which the check excludes) |
| ruff | "unused imports" | **39**, all but one in the vendored `deep-research-agent` |
| bandit (`-ll`) | not separated | 5 medium findings |
| SonarCloud | 7 blockers | 7 blockers (triaged in `docs/code-cleanup/README.md`) |

## Part A — ansible-lint (21 → 0)

### catchup-10-ansible-lint-fixes

```yaml
id: catchup-10-ansible-lint-fixes
title: Fix the 21 ansible-lint failures
depends_on: []

change: |
  Make exactly these edits and nothing else:

  1. terraform/lxc/ansible/playbooks/configure-ark-survival-ascended.yml,
     in ark_gameplay_settings: quote three values so YAML keeps them as the
     strings ARK expects (they're rendered into the INI via
     "{{ item.value }}", so the output is byte-identical):
       AllowUnlimitedRespecs: True       ->  AllowUnlimitedRespecs: "True"
       AllowFlyerCarryPvE: True          ->  AllowFlyerCarryPvE: "True"
       bUseSingleplayerSettings: False   ->  bUseSingleplayerSettings: "False"

  2. terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml and
     terraform/lxc/ansible/playbooks/deploy-cse-controller.yml: for every
     task whose ansible.builtin.command: runs `git` (remote rename,
     checkout -b, commit -am, submodule add/update; 2 tasks in cse-code-eval,
     10 in cse-controller), append two spaces and
     "# noqa: command-instead-of-module" to that task's
     "      ansible.builtin.command:" line. There is no git-module equivalent
     for these operations. (Placement verified: a noqa on the module line
     suppresses this rule.)

  3. Rename two tasks so the Jinja is at the end of the name:
     deploy-cse-controller.yml:
       "    - name: Create local cse-lab branch pinned to {{ cse_controller_repo_commit }} (plan §6 - never track main implicitly)"
       -> "    - name: Create local cse-lab branch (plan §6 - never track main implicitly) pinned to {{ cse_controller_repo_commit }}"
     deploy-cse-code-eval.yml:
       "    - name: Create local cse-lab branch pinned to {{ cse_code_eval_repo_commit }} (plan §6 - never track main implicitly)"
       -> "    - name: Create local cse-lab branch (plan §6 - never track main implicitly) pinned to {{ cse_code_eval_repo_commit }}"

  4. terraform/lxc/ansible/roles/lxc_tun_device/tasks/main.yml:
     - line "  check_mode: yes" -> "  check_mode: true"
     - line "        backup: yes" -> "        backup: true"
     - move the line "  when: tun_config_check.changed" (currently the last
       line of the "- name: Configure tun device if needed" task, after its
       block) to directly after "- name: Configure tun device if needed",
       before "  block:". The file must then end with the block's last
       line and a single newline (no trailing blank line, or yaml[empty-lines]
       fails).

  5. ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml:
     the unnamed task "    - ansible.builtin.set_fact:" becomes
     "    - name: Compute the new rule and anchor positions" followed on the
     next line by "      ansible.builtin.set_fact:" (keep its two keys
     unchanged under it).

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-ark-survival-ascended.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-controller.yml
    - terraform/lxc/ansible/roles/lxc_tun_device/tasks/main.yml
    - ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding rules to .ansible-lint skip_list or warn_list"
    - "Running any playbook"

gates:
  - id: lint-stack-playbooks
    cmd: "cd terraform/lxc/ansible && ansible-lint playbooks/"
    expect: "exit 0 ('0 failure(s)'; warnings allowed)"
    critical: true
  - id: lint-bootstrap-playbooks
    cmd: "cd ansible && ansible-lint 00-initial-setup/*.yml 01-base-system/*.yml"
    expect: "exit 0 ('0 failure(s)')"
    critical: true
  - id: syntax
    cmd: "cd terraform/lxc/ansible && for p in configure-ark-survival-ascended deploy-cse-code-eval deploy-cse-controller; do ansible-playbook --syntax-check -i localhost, playbooks/$p.yml || exit 1; done"
    expect: "exit 0"
    critical: true
```

## Part B — ruff, bandit, Sonar

### catchup-10-ruff-config-and-fixes

```yaml
id: catchup-10-ruff-config-and-fixes
title: Scope style rules for the vendored agent; remove real dead code; fix the mutable default
depends_on: []

change: |
  1. Create ruff.toml at the repo root with exactly this LITERAL content:

     # Repo-wide ruff settings (CI: validate.yml "Python lint + security").
     # Default rule set (E4, E7, E9, F) everywhere. The deep-research agent is
     # vendored from Local Agent Builder; its upstream style (late imports,
     # one-line ifs, `l` loop names) is kept to stay diffable against
     # upstream. Real defects (unused imports/variables) are still enforced.
     [lint.per-file-ignores]
     "terraform/lxc/ansible/files/deep-research-agent/**" = ["E402", "E701", "E741"]

  2. Run exactly:
       ruff check --fix terraform/lxc/ansible/files/deep-research-agent/src terraform/lxc/ansible/roles/es_findings_ingest/files/harbor_cleanup.py
       ruff check --fix --unsafe-fixes --select F841 terraform/lxc/ansible/files/deep-research-agent/src/engine/tui.py
     (the second keeps the right-hand side of `session_token = ...` as a
     bare expression, so any side effect is preserved).

  3. In terraform/lxc/ansible/files/deep-research-agent/src/engine/orchestrator.py
     replace
       available_sub_agents_ctx = contextvars.ContextVar('available_sub_agents_ctx', default=[])
     with
       available_sub_agents_ctx = contextvars.ContextVar('available_sub_agents_ctx', default=())
     (the value is only read and iterated; Sonar python:S8508).

scope:
  allowed_paths:
    - ruff.toml
    - terraform/lxc/ansible/files/deep-research-agent/src/
    - terraform/lxc/ansible/roles/es_findings_ingest/files/harbor_cleanup.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "ruff format (whole-file reformatting)"
    - "Hand-editing vendored code beyond items 2-3"

gates:
  - id: ruff-clean
    cmd: "git ls-files '*.py' | grep -v '_legacy/' | xargs ruff check"
    expect: "exit 0 ('All checks passed!')"
    critical: true
  - id: compiles
    cmd: "python3 -m compileall -q terraform/lxc/ansible/files/deep-research-agent/src terraform/lxc/ansible/roles/es_findings_ingest/files && echo ok"
    expect: "prints ok"
    critical: true
  - id: import-smoke
    cmd: "cd terraform/lxc/ansible/files/deep-research-agent/src && python3 -c \"import ast,pathlib;[ast.parse(p.read_text()) for p in pathlib.Path('.').rglob('*.py')];print('ok')\""
    expect: "prints ok"
    critical: true
```

### catchup-10-sonar-and-bandit

```yaml
id: catchup-10-sonar-and-bandit
title: Record the triaged Sonar false positives and bandit findings as scoped ignores
depends_on: []

change: |
  1. sonar-project.properties: append these four keys to the end of the
     existing comma-separated "sonar.issue.ignore.multicriteria=" line (keep
     the existing keys, add ",gaOidcTokenPipe,drFilesServeTraversal,secretsEnvRoleTraversal,gvmCredentialName")
     and append this LITERAL block at the end of the file:

     # Triaged 2026-09-28 (docs/code-cleanup/README.md, #434 gate failures):
     # githubactions:S8482 — pipes the GitHub OIDC token response to python json.load, not a downloaded executable
     sonar.issue.ignore.multicriteria.gaOidcTokenPipe.ruleKey=githubactions:S8482
     sonar.issue.ignore.multicriteria.gaOidcTokenPipe.resourceKey=.github/workflows/netbox-populate.yml
     # pythonsecurity:S2083 — paths are resolved and confined to the reports root before open()
     sonar.issue.ignore.multicriteria.drFilesServeTraversal.ruleKey=pythonsecurity:S2083
     sonar.issue.ignore.multicriteria.drFilesServeTraversal.resourceKey=terraform/lxc/ansible/files/deep-research-files/serve.py
     # pythonsecurity:S2083 — role name comes from the repo's own secrets/manifest.json profile, not user input
     sonar.issue.ignore.multicriteria.secretsEnvRoleTraversal.ruleKey=pythonsecurity:S2083
     sonar.issue.ignore.multicriteria.secretsEnvRoleTraversal.resourceKey=scripts/secrets_env.py
     # python:S6418 — "mikrotik-gvm-scan" is a GVM credential *name*, not a secret value
     sonar.issue.ignore.multicriteria.gvmCredentialName.ruleKey=python:S6418
     sonar.issue.ignore.multicriteria.gvmCredentialName.resourceKey=terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py

  2. Bandit (-ll): add an inline "  # nosec BXXX" comment, with the rule ID
     and nothing else, to exactly these lines:
     - terraform/lxc/ansible/files/deep-research-files/serve.py line 30 (B104:
       it runs in its own container behind Traefik forwardAuth, so binding
       all interfaces is required)
     - terraform/lxc/ansible/files/deep-research-files/serve.py line 43 (B108)
     - the two B310 urlopen lines in
       terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py
       (run `bandit -ll terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py`
       for the line numbers; the URLs are built from fixed http(s) endpoints)
     - terraform/lxc/stacks/cse-panel-stack/app/app.py line 561 (B608: it's
       an HTML page f-string, not SQL; checked 2026-09-28)

scope:
  allowed_paths:
    - sonar-project.properties
    - terraform/lxc/ansible/files/deep-research-files/serve.py
    - terraform/lxc/stacks/cse-controller/cyberseceval-config/
    - terraform/lxc/stacks/cse-panel-stack/app/app.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any code change other than the nosec comments"
    - "Suppressing any bandit finding not listed in item 2"

gates:
  - id: bandit-clean
    cmd: "git ls-files '*.py' | grep -v '_legacy/' | xargs bandit -ll -q"
    expect: "exit 0"
    critical: true
  - id: sonar-keys
    cmd: "grep -c -E 'multicriteria\\.(gaOidcTokenPipe|drFilesServeTraversal|secretsEnvRoleTraversal|gvmCredentialName)\\.ruleKey' sonar-project.properties"
    expect: "prints 4"
    critical: true
```

The four rule keys and files come from the #434 SonarCloud triage in
`docs/code-cleanup/README.md`. If the Sonar gate still fails after this lands,
the remaining issues are the lower-severity ones listed there (S5332 plain-HTTP
on internal traffic, S7493 sync `open()` in async code, S4423 TLS warnings).
Triage those on the SonarCloud issue page before adding more ignores.

## Part C — Harbor-only image references (needs redeploys)

### catchup-10-registry-host-compose

```yaml
id: catchup-10-registry-host-compose
title: Route cse-* and pterodactyl-lab images through ${REGISTRY_HOST}
depends_on: []

change: |
  1. In each of these compose files, replace the literal prefix
     "harbor.lab.gibbsgreatly.xyz/" at the start of every image: value with
     "${REGISTRY_HOST}/" (nothing else on those lines changes):
       terraform/lxc/stacks/cse-code-eval/docker-compose.yml      (1 line)
       terraform/lxc/stacks/cse-panel-stack/docker-compose.yml    (3 lines)
       terraform/lxc/stacks/cse-controller/docker-compose.yml     (2 lines)
       terraform/lxc/stacks/cse-kali/docker-compose.yml           (1 line)
  2. In terraform/lxc/stacks/pterodactyl-lab/docker-compose.yml change the
     three image: values exactly:
       mariadb:11                        -> ${REGISTRY_HOST}/dockerhub/library/mariadb:11
       redis:alpine                      -> ${REGISTRY_HOST}/dockerhub/library/redis:alpine
       ghcr.io/pterodactyl/panel:v1.15.1 -> ${REGISTRY_HOST}/ghcr/pterodactyl/panel:v1.15.1
  3. Make each stack's playbook write REGISTRY_HOST into that compose
     project's .env, so Compose substitutes it:
     - deploy-cse-panel-stack.yml, task "Write compose variable substitution
       file": change its content to
         content: "LAB_DOMAIN={{ lookup('env', 'LAB_DOMAIN') | mandatory('LAB_DOMAIN env var is required') }}\nREGISTRY_HOST={{ docker_registry_host }}\n"
     - deploy-cse-controller.yml, task "Write compose variable substitution
       file": change its content to
         content: "LAB_IP_CSE_PANEL={{ lookup('env', 'LAB_IP_CSE_PANEL') | mandatory('LAB_IP_CSE_PANEL env var is required') }}\nREGISTRY_HOST={{ lookup('env', 'LAB_FQDN_HARBOR') | mandatory('LAB_FQDN_HARBOR env var is required') }}\n"
     - deploy-pterodactyl-lab.yml, task "Write compose env file": add the
       line "          REGISTRY_HOST={{ docker_registry_host }}" directly
       after its "          LAB_DOMAIN={{ lookup('env', 'LAB_DOMAIN') }}" line.
     - deploy-cse-code-eval.yml and deploy-cse-kali.yml: directly before each
       file's task "    - name: Write docker-compose.yml to stack directory",
       insert this LITERAL task, with <DIR> replaced by
       "{{ cse_code_eval_stack_dir }}" or "{{ cse_kali_stack_dir }}"
       respectively:
           - name: Write compose variable substitution file
             ansible.builtin.copy:
               dest: "<DIR>/.env"
               mode: "0644"
               content: "REGISTRY_HOST={{ lookup('env', 'LAB_FQDN_HARBOR') | mandatory('LAB_FQDN_HARBOR env var is required') }}\n"

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-code-eval/docker-compose.yml
    - terraform/lxc/stacks/cse-panel-stack/docker-compose.yml
    - terraform/lxc/stacks/cse-controller/docker-compose.yml
    - terraform/lxc/stacks/cse-kali/docker-compose.yml
    - terraform/lxc/stacks/pterodactyl-lab/docker-compose.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-controller.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-kali.yml
    - terraform/lxc/ansible/playbooks/deploy-pterodactyl-lab.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing any image tag or digest"
    - "Running any playbook"

gates:
  - id: no-literal-registry
    cmd: "grep -nE 'image: *(harbor\\.lab\\.gibbsgreatly\\.xyz/|mariadb:|redis:|ghcr\\.io/)' terraform/lxc/stacks/{cse-code-eval,cse-panel-stack,cse-controller,cse-kali,pterodactyl-lab}/docker-compose.yml || echo none"
    expect: "prints none"
    critical: true
  - id: compose-config
    cmd: "for s in cse-code-eval cse-panel-stack cse-controller cse-kali pterodactyl-lab; do REGISTRY_HOST=harbor.example LAB_DOMAIN=x LAB_IP_CSE_PANEL=1.2.3.4 PTERODACTYL_LAB_DB_PASSWORD=x PTERODACTYL_LAB_DB_ROOT_PASSWORD=x docker compose -f terraform/lxc/stacks/$s/docker-compose.yml config -q || exit 1; done; echo ok"
    expect: "prints ok (compose files still valid with REGISTRY_HOST set)"
    critical: false
  - id: syntax
    cmd: "cd terraform/lxc/ansible && for p in deploy-cse-panel-stack deploy-cse-controller deploy-cse-code-eval deploy-cse-kali deploy-pterodactyl-lab; do ansible-playbook --syntax-check -i localhost, playbooks/$p.yml || exit 1; done"
    expect: "exit 0"
    critical: true
```

`compose-config` is `critical: false` because it needs Docker on the machine
running it. Standing preference: don't run local Docker on the operator's
workstation. Skip it there; the redeploys below validate the same thing for
real.

### Operator: redeploy (Ansible-task tier, directly on the owning node)

The image *content* doesn't change (same tags, pulled through the Harbor
proxy caches the torrent stack already uses), but the image *reference*
does, so Compose recreates each container once.

```bash
# pve-tiny (memory: reference_cse_panel_stack_pve_tiny_wrapper — must be the -tiny wrapper)
TASK_APPROVAL=catchup-10-redeploy-cse ./with-secrets-prod-tiny scripts/provision.sh --stack cse-panel-stack
TASK_APPROVAL=catchup-10-redeploy-cse ./with-secrets-prod-tiny scripts/provision.sh --stack cse-controller
TASK_APPROVAL=catchup-10-redeploy-cse ./with-secrets-prod-tiny scripts/provision.sh --stack cse-code-eval
# pve — Panel only; game servers run under Wings on gaming-stack-lab and are untouched
TASK_APPROVAL=catchup-10-redeploy-pterodactyl ./with-secrets-prod scripts/provision.sh --stack pterodactyl-lab
# cse-kali lives on pve-test (dev environment, STACK_CONTRACT.md) — no production approval
PVE_ENV=pve-test ./with-secrets scripts/provision.sh --stack cse-kali
```

Before the cse redeploys, check no benchmark job is running in the CSE panel.
Before the Pterodactyl redeploy, check nobody is using the Panel. Verify:
`https://pterodactyl.lab.gibbsgreatly.xyz/` logs in, and the CSE panel lists
past runs.

## Done when

- On the next PR into `stable`, "Ansible lint", "Python lint + security",
  "Enforce Harbor-only image references" and "SonarCloud analysis" pass.
- The redeploys are recorded in the hand-back.
- `docs/code-cleanup/README.md`'s #434 gate section gets one line: "Fixed in
  docs/catch-up/10."
