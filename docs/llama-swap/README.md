# llama-swap (workspace)

A web control page for choosing which model and llama.cpp build Framework
serves on :8080. See [plan.md](plan.md).

Status: **phase 1 done, 2026-10-07.** llama-swap is running idle on :8099;
the hand-run GLM still serves :8080. Phase 2 (cutover) waits for the operator.

## Log

- 2026-10-07: design changed to "control page only". Clients keep using
  `llama-server` on :8080 directly; llama-swap listens on :8099. Files:
  - `ansible/00-initial-setup/framework-desktop-llama-swap.yml`
  - `ansible/00-initial-setup/files/llama-swap/{config.yaml,llm-memgate}`
  - the chat guard in `framework-desktop-llamacpp-native.yml`
- 2026-10-07: phase 1 run (`TASK_APPROVAL=llama-swap-install`): ok=19
  changed=12 failed=0, cutover tasks skipped. Verified afterwards:
  - `llama-swap` is active on :8099 and returns 401 without the key; it
    lists the three models, none loaded.
  - GLM (pid 1621293) still serves :8080, `/health` ok.
  - Embeddings on :8085 are unchanged.
  - `nathanw-llamacpp` is still inactive but enabled (disabled at cutover).
