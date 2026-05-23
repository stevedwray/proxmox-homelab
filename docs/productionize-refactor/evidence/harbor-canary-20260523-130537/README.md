# Harbor Stack Production Canary — 2026-05-23

## Summary
Harbor v2.14.3 deployed to production pve as VMID 40010 at 192.168.40.10.

## Phase Results
- Phase 0: pve-test counterpart disposed (container absent, state cleared)
- Phase 1: Terragrunt apply — 5 resources created on pve
- Phase 2: Ansible --check — 25 ok, 10 changed, 0 failed
- Phase 3: Live provisioning — 68 ok, 18 changed, 0 failed
- Phase 4: All health gates PASS

## Health Gate Results
- Docker ps: 10 Harbor services + portainer-agent, all healthy
- API ping: Pong
- Proxy registries: docker-hub, ghcr, quay, lscr — all healthy
- System info: Harbor v2.14.3, auth_mode=oidc_auth, read_only=False

## Notes
- OIDC Authentik reconcile deferred (Authentik not reachable at reconcile time — expected)
- CI robot account created: robot$ci-runner (save secret to Bitwarden)
- Breakglass: built-in admin account (local user creation blocked in oidc_auth mode)
