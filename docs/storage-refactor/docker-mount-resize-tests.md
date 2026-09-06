# Docker Mount Resize Tests

This workflow is the repo-native Day 2 proof for Docker-backed LXC stacks that
grow `/var/lib/docker` operationally and then prove the source of truth still
matches live state.

## Target stacks

- `proxy-stack`
- `authentik-stack`
- `harbor-stack`
- `monitoring-stack`
- `netbox-stack`
- `portainer-stack`

These are the Docker-backed service LXCs that now declare canonical
`docker_mount` intent with:

- `path: /var/lib/docker`
- `resize_control_plane: operational`
- `mutation_policy: grow-only`

For the current pve-test fleet, that operational path is now validated on both
supported live backends in this repo:

- `infrastructure-containers` (`zfs`)
- `local-lvm` (`lvm-thin`)

## Test contract

For each stack, the test must prove all of the following:

1. the desired Docker mount size in `stack.yaml` is larger than the live size
2. `scripts/resize-lxc-mount.sh --stack <name> --require-grow` performs a real
   Proxmox `pct resize` on the Docker mount
3. `terragrunt plan -detailed-exitcode -no-color` returns exit `0` afterward,
   which proves no Terraform drift remains
4. the container is still healthy after the resize

## How to run a single stack

1. Update both `docker_mount.size` and `docker_storage_size` in the target
   stack's `stack.yaml` to the same larger value.
2. Run:

```bash
./with-secrets bash -lc './scripts/test-docker-mount-resize.sh --stack authentik-stack'
```

Logs are written under `/tmp/docker-mount-resize-<timestamp>/` by default.

## How to run the full stack set

After updating each target stack's desired Docker size to a larger value, run:

```bash
./with-secrets bash -lc './scripts/test-docker-mount-resize.sh'
```

The wrapper runs each stack in sequence and stops on the first failure.

## Notes

- This workflow is intentionally grow-only. It does not support shrink.
- The wrapper expects to run under `./with-secrets` and will fail if
  `TF_VAR_proxmox_node` is not `pve-test`.
- `terragrunt plan -detailed-exitcode` is used for drift detection because exit
  `2` is an exact signal that the resize left Terraform-visible changes behind.
- **`resize-lxc-mount.yml` was broken against production until 2026-08-17.**
  Its `proxmox_delegate_host` var defaulted to itself
  (`proxmox_delegate_host | default(pve_host | default(...), true)`), which
  only ever resolved when the caller also injected a same-named `-e`
  extra-var (as `resize-lxc-mount.sh` does when `PVE_TEST_FQDN` is set —
  extra-vars outrank play vars and short-circuit the template entirely).
  Against production `pve`, with no such extra-var, Ansible had to resolve
  the play var against itself and recursed infinitely ("Recursive loop
  detected in template"). This is why the target-stack list above and the
  "fails if not `pve-test`" note only ever covered `pve-test` — this was
  the first real production run of this tooling. Fixed by referencing
  `pve_host` directly instead of the self-named var; extra-var overrides
  still work exactly as before.
- **The script assumes the legacy `terraform/lxc/stacks/<name>/inventory.yml`
  layout.** Stacks already migrated to the per-environment layout (e.g.
  `terraform/lxc/environments/pve/<name>/inventory.yml` — see
  `docs/environment-isolation/`) don't have an `inventory.yml` in the
  legacy location at all. Until the script itself is updated to check both
  layouts, copy the real inventory file into the legacy path before
  running, and remove the copy afterward (both locations are gitignored,
  so this is safe/ephemeral either way). First hit doing `greenbone-stack`'s
  resize.
