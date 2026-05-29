# First Extra-Mount Attach Tests

This workflow is the repo-native proof for adding the first persistent extra
mount to an existing Docker-only LXC without applying the provider's direct
replacement-sensitive path.

## Target containers

- `test-storage` for the Docker-only to first-extra-mount transition
- `test-storage-extra` for regression checks on the existing-extra-mount path

## Test contract

The additive attach proof must show all of the following on `test-storage`:

1. the stack starts with no live extra mount in `pct config`
2. the desired first `extra_mount` is declared in `stack.yaml`
3. a direct Terraform/OpenTofu plan surfaces the provider's
   replacement-sensitive path and is not applied
4. `scripts/resize-lxc-mount.sh --stack test-storage --mount-path <path>`
   attaches the first extra mount live through `pct set`
5. the playbook blocks mount-over-existing-data by default
6. the guest can write sentinel data on the new filesystem
7. a follow-up module-scoped
   `terragrunt plan -target=module.lxc -no-color` shows no storage-related
   drift for the attached mount

The regression check on `test-storage-extra` must still show the existing
extra-mount workflow behaving correctly for a no-op or grow-only run.

## Verified proof sequence

The current live proof used these commands:

```bash
./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack test-storage --mount-path /srv/test-extra-attach'
./with-secrets bash -lc "ssh -F /dev/null root@${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz} 'pct exec 150 -- sh -lc \"echo attach-proof > /srv/test-extra-attach/.sentinel && ls -la /srv/test-extra-attach && df -h /srv/test-extra-attach\"'"
./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -target=module.lxc -no-color'
./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack test-storage-extra --mount-path /srv/test-extra'
```

Key observed results:

- `test-storage` attached
  `mp1: infrastructure-containers:subvol-150-disk-3,mp=/srv/test-extra-attach,backup=0,size=8G`
- guest `df -h /srv/test-extra-attach` reported `8.0G`
- sentinel data write on `/srv/test-extra-attach` succeeded
- the follow-up `terragrunt plan -target=module.lxc -no-color` on
  `test-storage` showed no storage diff for the attached mount
- `test-storage-extra` still passed a practical no-op verification run against
  `/srv/test-extra`

Backup-policy note:

- the attach workflow now derives the Proxmox `backup=` flag from the declared
  `extra_mount.backup_policy`
- `include` renders `backup=1`
- `exclude` renders `backup=0`
- older proof output that showed `backup=0` for an attached mount reflected the
  pre-backup-intent implementation state, not a permanent contract default

## Notes

- The direct provider plan for first extra-mount introduction remains
  replacement-sensitive on the current provider and must still be treated as a
  stop condition for apply.
- `test-storage` currently has a separate pre-existing SDN-attachment diff in
  the root stack, so the authoritative post-attach storage check is the
  module-scoped `terragrunt plan -target=module.lxc -no-color` run rather than
  a full-stack no-op claim.
- If you remove a proof mount from a running disposable test CT with
  `pct set <vmid> -delete mp1`, restart the CT before attempting another attach
  proof on the same path; otherwise the guest can retain a stale mounted path
  and the path-safety check will correctly block the reattach.
