# 02 — Repo hygiene

**When:** today · **Effort:** 45 min · **Value:** Medium
**Production access:** none (GitHub and the local checkout only)

Everything here is git/GitHub housekeeping. Opening and merging PRs is the
operator's call (standing preference: don't auto-PR or auto-merge), so this is
an operator checklist with exact commands, not step blocks.

## State on 2026-09-28

- `origin/stable` (`62e91a7c`) is an ancestor of `origin/main` (`4589bacd`,
  the #434 merge commit). Local `stable` (`4c4212fe`) is behind both.
- Five branches carry work not on `main`. Each merges into `origin/stable`
  with no conflicts (`git merge-tree` dry run, 2026-09-28):

  | Branch | Content | Pushed? | Why merge |
  |---|---|---|---|
  | `fix/ark-update-workaround` | ARK egg `rm -f appmanifest` + `update-ark-survival-ascended.yml` | no | The egg change is **already live** (verified 2026-09-28); the repo lags |
  | `task/dns-stack-daemon-json-audit` | `docs/dns-refactor/daemon-json-audit.md` + graylog `STACK_CONTRACT.md` fix | yes | Audit result verified live |
  | `task/docker-log-driver-audit` | `docs/logging/…` audit (500 lines) | yes | Docs only |
  | `task/ci-gate-followups` | `docs/code-cleanup/README.md` CI-gate triage | no | Docs only |
  | `task/status-refresh-2026-09-28` | Status refresh of 10 workspace docs | no | Docs only |
  | `task/catch-up-plans` | This workspace | no | Docs only |

- Seven branches are fully contained in `main` and can go:
  `feat/secrets-openbao`, `fix/netbox-populate-no-docker`,
  `task/ai-stacks-pve-tiny`, `task/framework-dns-only-plan`,
  `task/framework-reip-cutover`, `task/retire-sops`,
  `task/secrets-refactor-design`.
- Two agent worktrees under `.claude/worktrees/` hold the two audit branches.

## Operator checklist

### 1. Sync local `stable`

```bash
git fetch origin
git switch stable && git merge --ff-only origin/stable && git switch -
```

Expect a fast-forward to `62e91a7c`.

### 2. Push and open PRs into `stable`

`fix/ark-update-workaround` is a real Ansible/egg change. Before its PR, run
the gate CLAUDE.md requires for any Ansible edit:

```bash
git switch fix/ark-update-workaround
(cd terraform/lxc/ansible && ansible-playbook --syntax-check playbooks/update-ark-survival-ascended.yml)
python3 -c "import json;json.load(open('docs/gaming-stack-lab/ark-survival-ascended-egg.json'));print('egg json ok')"
git switch -
```

Then, per branch (one PR each keeps review small):

```bash
for b in fix/ark-update-workaround task/dns-stack-daemon-json-audit task/docker-log-driver-audit task/ci-gate-followups task/status-refresh-2026-09-28 task/catch-up-plans; do
  git push -u origin "$b"
  gh pr create --base stable --head "$b" --fill
done
```

**Validation tier:** `fix/ark-update-workaround` is "Ansible task or role
changes", but its egg change is already running live (Panel-edited), and the
playbook runs only when the operator triggers it. There's nothing further to
deploy for promotion to `stable`. The docs branches need no validation.

Merging is the operator's call. Merge in the table's order so the later docs
branches rebase cleanly if needed.

### 3. Delete the seven merged branches

Confirm each is really contained first (prints nothing if so):

```bash
for b in feat/secrets-openbao fix/netbox-populate-no-docker task/ai-stacks-pve-tiny task/framework-dns-only-plan task/framework-reip-cutover task/retire-sops task/secrets-refactor-design; do
  git log --oneline --no-merges origin/main.."$b" | sed "s|^|$b: |"
done
```

Then delete:

```bash
for b in feat/secrets-openbao fix/netbox-populate-no-docker task/ai-stacks-pve-tiny task/framework-dns-only-plan task/framework-reip-cutover task/retire-sops task/secrets-refactor-design; do
  git branch -d "$b"
  git ls-remote --exit-code --heads origin "$b" >/dev/null && git push origin --delete "$b"
done
```

`git branch -d` (not `-D`) refuses if a branch isn't merged. Treat a refusal
as "stop and look", not "force it".

### 4. Remove the two agent worktrees (after their PRs merge)

```bash
git worktree list
git worktree remove .claude/worktrees/agent-a6de66eea7fdc86b5   # task/docker-log-driver-audit
git worktree remove .claude/worktrees/agent-ac03abeb2d444324c   # task/dns-stack-daemon-json-audit
git worktree prune
```

### 5. Delete the merged catch-up/status branches once their PRs land

```bash
for b in fix/ark-update-workaround task/dns-stack-daemon-json-audit task/docker-log-driver-audit task/ci-gate-followups task/status-refresh-2026-09-28; do
  git branch -d "$b" && git push origin --delete "$b"
done
```

Keep `task/catch-up-plans` until this workspace is closed out, or delete it
after merge. The plans live on `stable` from then on.

## Done when

- `git branch -a --no-merged origin/stable` lists only `baseline/*`,
  `prod/pve-infra` and whatever is actively in progress.
- `git worktree list` shows only the main checkout.
- Hand-back in `README.md` lists the PR numbers.
