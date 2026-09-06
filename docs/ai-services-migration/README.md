# AI Services Migration

Status: **Steps 1–6 done and validated on `pve-test-vm`, not promoted.**
See [current-state.md](current-state.md) for the checkpoint: live
state, what's been validated and how, real bugs found and fixed during
implementation, and next steps.

Plan to move OpenWebUI + SearXNG off `framework.gibbsgreatly.xyz` (bare-metal
GPU host, currently running them as flat-LAN Docker containers) onto a
dedicated `ai-services-stack` LXC on `pve`, validated first on
`pve-test-vm`, in the `ai_seg` zone (VLAN 50) alongside the existing
`mcp-utility-stack`. Leaves `framework` running only things directly tied
to serving/storing AI models — `llamacpp-router`, `ollama`, `comfyui`
(needs local GPU access, stays put), and the model files themselves.

See [plan.md](plan.md) for the full design: current-state inventory, why
the old `terraform/lxc/stacks/{llm-gpu-stack,comfyui-stack,ai-services-stack}/`
scaffolding is stale and shouldn't be reused, the concrete migration
steps, and open questions to resolve during implementation. Temporary
handoffs/notes belong in the ignored `artifacts/` directory.
