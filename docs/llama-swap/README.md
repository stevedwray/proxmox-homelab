# llama-swap (workspace)

A web control page for choosing which model and llama.cpp build Framework
serves on :8080. See [plan.md](plan.md).

Status: **phase 1 (install, idle) in progress, 2026-10-07.** The hand-run GLM
still serves :8080.

## Log

- 2026-10-07: design changed to "control page only". Clients keep using
  `llama-server` on :8080 directly; llama-swap listens on :8099. Files:
  - `ansible/00-initial-setup/framework-desktop-llama-swap.yml`
  - `ansible/00-initial-setup/files/llama-swap/{config.yaml,llm-memgate}`
  - the chat guard in `framework-desktop-llamacpp-native.yml`
