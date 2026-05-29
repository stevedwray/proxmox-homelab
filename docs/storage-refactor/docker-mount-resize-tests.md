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
