TASK REPORT
Task id: 21
Status: blocked

Branch state:
- Branch: fix/task-21-pct-stop-compat-main
- Cut from dev/pve-test: no
- Commit made: no
- Commit SHA: none
- Merge target: dev/pve-test
- Merge-ready: no

Files changed:
- scripts/rebuild-gate-destroy.sh
- docs/refactor-remove-portainer/reports/21-pct-stop-compatibility-fix-report.md

Preflight:
- Command: ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
- Result: pass
- Notes: Returned pve-test.
- Command: test -f docs/refactor-remove-portainer/reports/20a-rebuild-gate-with-corrected-evidence-handling-report.md && echo present
- Result: pass
- Notes: Returned present.

Source-only validation:
- Command: ./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct help stop | sed -n "1,120p"'
- Result: pass
- Notes: Help output lists --overrule-shutdown and --skiplock; no --timeout support on this host.
- Command: shellcheck scripts/rebuild-gate-destroy.sh
- Result: pass
- Notes: No shellcheck findings emitted.
- Command: ./scripts/rebuild-gate-destroy.sh --dry-run
- Result: pass
- Notes: Preflight passed, scope rendered from stack.yaml, and destroy command remained stack-only terragrunt run --all destroy.

Task-complete validation:
- Command: ./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 150'
- Result: pass
- Notes: Returned status: running before live stop attempt.
- Command: timeout 45s ./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct stop '150'"; rc=$?; echo stop_rc=$rc; ./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 150'
- Result: fail
- Notes: No Unknown option/400 parse error. New live failure: trying to acquire lock... can't lock file '/run/lock/lxc/pve-config-150.lock' - got timeout (stop_rc=255); status remained running.
- Command: git status --short --branch
- Result: pass
- Notes: Branch is fix/task-21-pct-stop-compat-main with scoped edit plus pre-existing local workspace changes/hazards.
- Command: ./with-secrets /home/steve/.local/bin/sonar-scanner
- Result: pass
- Notes: ANALYSIS SUCCESSFUL, EXECUTION SUCCESS; no new scanner failure.

Stop conditions:
- Triggered: yes
- Details: Validation revealed a different live stop-path failure beyond the option parsing defect (LXC config lock timeout on vmid 150).

Behavioral outcome:
- scripts/rebuild-gate-destroy.sh stop-first command now uses host-compatible pct stop '<vmid>' (unsupported --timeout removed).
- The original Task 20a defect (Unknown option: timeout / 400 unable to parse option) is no longer present in validation output.
- Full rebuild gate was not rerun in this task.

Unexpected findings outside task boundary:
- dev/pve-test baseline in clean worktrees did not include scripts/rebuild-gate-destroy.sh yet, while the active integration line does; this was not changed in this task.
- Existing local tracked/untracked workspace changes predate this task and were preserved.

Recommended disposition:
- blocked pending architecture update
