# Foreverworld migration to Wings

This is the execution runbook for moving the existing Wildworks
Foreverworld server from its Portainer-owned Compose project into
Pterodactyl Wings. The source is copied, never moved, and remains the
rollback source until the operator explicitly retires it.

The host has enough memory for one large game, not ARK and Minecraft at
the same time. The migration therefore includes a hard, race-safe game-slot
interlock. Do not start either Wings server until both have the shared mount
and interlocked egg startup configured.

## Checked-in artifacts

- `wildworks-neoforge-egg.json`: custom PTDL v2 egg. It uses Java 21 and
  launches the modpack's own `run.sh`; it does not reinstall or reinterpret
  the pre-built pack.
- `ark-survival-ascended-egg.json`: the live ARK egg with the same interlock
  prefix added to its startup command.
- `deploy-gaming-stack-lab.yml`: creates the host lock, allow-lists its mount
  in Wings, reconciles all Minecraft/ARK allocations, and declares 100%
  memory over-allocation for fresh nodes.

The interlock opens `/game-slot/active.lock`, takes a non-blocking `flock`,
and holds its file descriptor for the game process lifetime. A competing
start exits with code 75 and prints `GAME SLOT BUSY`. Kernel-owned locks are
released on normal exit, crash, or forced container termination; there is no
stale lock-file cleanup path.

## Phase 0: repository gates

Run before any production change:

```bash
jq -e '.meta.version == "PTDL_v2" and (.startup | contains("flock -n -E 75"))' \
  docs/gaming-stack-lab/wildworks-neoforge-egg.json \
  docs/gaming-stack-lab/ark-survival-ascended-egg.json
cd terraform/lxc/ansible
ansible-playbook --syntax-check playbooks/deploy-gaming-stack-lab.yml
```

The Java 21 and Proton 8 images must both contain `/usr/bin/flock`. Verify
that on the Wings host before changing either egg. A missing binary is a stop
condition, not permission to start without the interlock.

## Phase 1: live read-only preflight

Record all results in the session before asking for mutation approval:

1. Confirm ARK state and that the old Foreverworld Compose project is stopped.
2. List Panel servers, eggs, node allocations, and the node's current memory
   over-allocation value.
3. Inventory every top-level item under
   `/srv/docker/minecraft/foreverworld`; record total size, file count, mod
   count, world `level.dat`, playerdata count, `run.sh`,
   `user_jvm_args.txt`, `libraries/`, `defaultconfigs/`, and any pack-specific
   directories such as `kubejs/` or `scripts/`.
4. Inspect `user_jvm_args.txt` and the release-native `run.sh`. The current
   deployment has a 16 GiB Java heap; the Wings server limit must include JVM
   and native overhead rather than equalling the heap exactly.
5. Confirm `25565` and `25575` exist and are unassigned. Confirm the ARK
   allocations remain assigned only to ARK.
6. Determine the real source filesystem/dataset and an appropriate snapshot
   command. Do not guess the ZFS dataset name from the guest path.

Any unexpected running container, missing pack directory, allocation
collision, or unaccounted top-level source item stops the migration.

### Recorded preflight — 2026-09-26

- Foreverworld is stopped; ARK is the only running game container.
- Source size is 7.4 GiB across 3,939 files, with 253 active mod files.
  `level.dat` is owned by `1000:1000`, mode `0600`, and was last modified
  2026-09-20 09:39 +1200.
- The complete source includes release-critical `run.sh`,
  `user_jvm_args.txt`, `libraries/`, `defaultconfigs/`, `config/`,
  `dynamic-data-pack-cache/`, `moonlight-global-datapacks/`,
  `patchouli_books/`, `villagerpacks/`, and `world.pre-regenerate/`, in
  addition to the expected world/mod/config files. The reviewed manifest
  must preserve these unless a later inventory explicitly classifies one.
- `user_jvm_args.txt` sets `-Xms16G -Xmx16G`, GC logging, and the JMX
  exporter. `run.sh` invokes NeoForge `21.1.234`'s `unix_args.txt`.
- The source mount is ZFS dataset `gaming/subvol-60010-disk-0`, mounted at
  `/gaming/subvol-60010-disk-0` on `pve`; it has 481 GiB available. This is
  the exact dataset to snapshot before copying.
- ARK is a 16,384 MiB/150,000 MiB server on node 1; its Proton 8 container
  has `/usr/bin/flock`. Node 1 still has 0% memory over-allocation, so it
  must be raised before the 16 GiB Minecraft definition can be created.
- Allocation `25565` is free. Allocation `25575` is absent and will be
  added by the targeted provision run.

## Phase 2: install the interlock infrastructure

This is a production mutation and uses the normal preflight/approval flow.
Run the targeted stack provision against `pve`; do not use pve-test-vm for
this application-level change.

Expected effects:

- `/srv/docker/pterodactyl/game-slot/active.lock` exists as root-owned `0444`.
- Wings `allowed_mounts` contains only
  `/srv/docker/pterodactyl/game-slot` for this feature.
- Wings restarts only if its configuration changes.
- Missing allocations, including `25575`, are added without recreating or
  reassigning existing allocations.

Because the node already exists, set its memory over-allocation to `100` in
Panel Admin after provisioning; the playbook's create body only governs a
fresh node. This permits the current 16 GiB ARK definition and a suitably
sized Minecraft definition to coexist in Panel. It is safe only while the
runtime interlock is mandatory for every game on the node.

### Completed production stage — 2026-09-26

- The host lock directory and `/srv/docker/pterodactyl/game-slot/active.lock`
  now exist on the dedicated game-data mount as root-owned `0755`/`0444`.
- Wings is active with `/srv/docker/pterodactyl/game-slot` in
  `allowed_mounts`.
- Node 1's `memory_overallocate` is now `100`; its 24,576 MiB memory and
  500,000 MiB disk limits were preserved.
- Allocation `25575` was created free alongside the already-free `25565`.
  All four ARK allocations remain assigned to ARK, which remained running
  throughout this stage.

The host-side capability is now installed, but it is not an active runtime
interlock until Phase 3 assigns the mount and updated startup definition to
both ARK and Minecraft, then Phase 7 proves rejection in both directions.

## Phase 3: Panel-admin setup

Pterodactyl does not expose egg import or server-mount assignment through the
Application API. Perform these steps in Panel Admin and record the resulting
IDs:

1. Stop ARK.
2. Update ARK's existing egg startup from the checked-in
   `ark-survival-ascended-egg.json`. Do not merely import a duplicate egg and
   leave the live server on the old one.
3. Create one mount:
   - source: `/srv/docker/pterodactyl/game-slot`
   - target: `/game-slot`
   - read only: yes
   - assignable to the gaming node and both relevant eggs
4. Assign that mount to the existing ARK server.
5. Import `wildworks-neoforge-egg.json` and assign the same mount to it.
6. Start ARK once. Confirm `/usr/bin/flock` exists, normal startup succeeds,
   and the lock is visibly held. Stop ARK cleanly and confirm it releases.

Do not create or start Minecraft if ARK has not passed this gate.

### Completed production stage — ARK interlock verified, 2026-09-26

Egg 15 (`ARK: Survival Ascended`) and the existing ARK server's own cached
startup both exactly match the checked-in interlocked startup (SHA-256
`14f54377cd666b8dccd5034b9d2beba589f9e7329772d2c4c34d5c55ed664a17`).
The existing server required an explicit association with mount 1 in
`mount_server`; egg/node mount associations alone are not retroactive for an
already-created server.

After the controlled restart, its live container has the read-only host mount
at `/game-slot`, completed normal startup and is advertising for join. A
second non-blocking host lock attempt returned exit code `75`, proving that
ARK holds the shared game-slot lock. Do not alter the ARK egg or its per-server
startup without preserving this prefix.

## Phase 4: create an unstarted Minecraft staging server

Use the Application API only after the manual egg import. Create the server
on the existing gaming node with:

- primary allocation `25565`, secondary allocation `25575`;
- Java 21 image from the checked-in egg;
- memory limit greater than the preserved 16 GiB heap so native/JVM overhead
  is not forced inside the heap limit (final value comes from Phase 1);
- swap disabled unless the operator explicitly chooses otherwise;
- enough disk for the measured source plus update/backup headroom;
- `start_on_completion: false`.

Wait for installation success. The staging installer only creates an EULA
file and `MIGRATION_REQUIRED.txt`; it intentionally does not download another
NeoForge server. Record the server ID, short identifier, full UUID, and exact
Wings volume path. Assign the shared mount before any start attempt.

### Completed production stage — unstarted Minecraft staging server, 2026-09-26

Panel server 3, `Foreverworld (migration staging)`, is installed but has not
been started. Its full UUID is `aa27bd44-577c-473e-94d3-d3f04a63c1c0` and its
short identifier is `aa27bd44`. It uses egg 16, allocation 1 (`25565`) and
allocation 6 (`25575`), with 18,432 MiB memory, zero swap, and 50,000 MiB
disk. Its empty Wings volume is
`/srv/docker/pterodactyl/volumes/aa27bd44-577c-473e-94d3-d3f04a63c1c0` and
contains only the intentional installer markers `eula.txt` and
`MIGRATION_REQUIRED.txt`.

As with the pre-existing ARK server, the mount required an explicit
`mount_server` association. Server 3 is now associated with mount 1
(`game-slot-lock`); do not start it until the Phase 5 copy and Phase 6
configuration gates are complete.

## Phase 5: freeze, snapshot, and copy

1. Confirm ARK and the new Minecraft server are stopped.
2. Stop the complete old Foreverworld Compose project. Set its existing
   containers' restart policy to `no` so a host reboot cannot create a second
   writer during the confidence period. Keep the Compose files intact.
3. Confirm nothing listens on `25565` or `25575`.
4. Take the Phase 1 snapshot/backup and verify that it exists.
5. Copy the complete reviewed server manifest, not a hand-picked list of only
   `world/`, `mods/`, and `config/`. The default exclusions are Compose and
   monitoring ownership artifacts:

   ```text
   /compose.yaml
   /docker-compose.yml
   /Dockerfile
   /docker-entrypoint.sh
   /jmx-exporter/
   /MIGRATION_REQUIRED.txt
   ```

   Add an exclusion only if Phase 1 classified it and recorded why. Preserve
   ACLs, xattrs, hard links, and numeric ownership during the copy.
6. Inspect the target Java image's effective `container` UID:GID, recursively
   apply it to the destination, and prove that exact image user can create and
   remove a test file. Do not assume the source Compose UID:GID or an existing
   ARK volume's ownership is correct.
7. Checksum the exact same manifest with `rsync --archive --hard-links
   --acls --xattrs --numeric-ids --checksum --dry-run` and the identical
   exclusion list. The result must contain no source-to-destination changes.

Never use `--delete` against the source. Never rename or remove the source.

### Completed production stage — source frozen and copied, 2026-09-26

The old Foreverworld Compose project had no containers and remains stopped.
No staging Minecraft container is running. A new rollback snapshot exists at
`gaming/subvol-60010-disk-0@before-pterodactyl-minecraft-copy-20260926`.

The complete reviewed source was copied one-way from
`/srv/docker/minecraft/foreverworld/` into server 3's Wings volume using
`rsync --archive --hard-links --acls --xattrs --numeric-ids`, without
`--delete`, and with only the documented Compose/monitoring exclusions. The
checksum dry-run reported no content changes after the copy. The source has
3,939 files; the destination has 3,936 files after those exclusions.

The Java 21 image's `container` user is UID:GID `1001:1001`, not the
ARK-volume UID:GID. The migrated volume is therefore recursively owned by
`1001:1001`; its `world/level.dat` remains mode `0600`. A disposable
Java-image create/remove probe passed. The existing `eula=true` acceptance was
preserved from the previously running source, without a new acceptance action.

## Phase 6: secrets and first start

1. Set `eula=true` only after confirming acceptance.
2. Preserve the reviewed `server.properties`, including `enable-rcon=true`,
   `rcon.port=25575`, whitelist, seed, difficulty, and distance settings.
3. Inject `MINECRAFT_FOREVERWORLD_RCON_PASSWORD` from SOPS into
   `server.properties` without printing it or placing it in the egg/API body.
4. Confirm `run.sh` is executable and the preserved JVM arguments match the
   approved heap and optional JVM flags. Remove the old Compose-only
   `/data/jmx-exporter` Java-agent option when that directory is excluded;
   retain the 16 GiB heap and GC logging.
5. Start Minecraft from Panel while watching the live console. Stop on
   missing mods, registry errors, wrong world selection, ownership errors, or
   an unexpected new-world generation.

Required gates before cutover is considered successful:

- the server reaches its ready message;
- TCP `25565` accepts a connection and RCON succeeds on `25575`;
- expected mod count, world identity, representative player files, and
  pack-specific directories match;

### Completed production stage — first Minecraft start, 2026-09-26

ARK was stopped cleanly and released the shared lock before the first staging
start. The copied JVM arguments initially referenced the intentionally
excluded Compose-only `/data/jmx-exporter` Java agent, so Java exited before
opening a port. Removing only that argument (while retaining `-Xmx16G`,
`-Xms16G`, and GC logging) corrected the migration-specific startup issue.

Minecraft then completed NeoForge startup, holds the game-slot lock, listens
on `25565` and `25575`, and accepted an authenticated RCON `list` command.
The preserved source and destination both have 243 mod JARs, one player-data
file, and byte-identical `world/level.dat`. The source remains stopped and
the rollback snapshot remains available.
- the operator verifies world, builds, inventories, whitelist, and key mod
  behavior in-game;
- a normal stop/start cycle succeeds;
- a Wings backup or separately documented restore test succeeds.

## Phase 7: prove mutual exclusion

With Minecraft running, request an ARK start from the normal Panel UI. ARK
must remain stopped and its console must show `GAME SLOT BUSY`. Then stop
Minecraft, start ARK, and request a Minecraft start. Minecraft must fail the
same way. Finally, stop ARK and start Minecraft normally.

This two-direction test is mandatory. A successful single-server start does
not prove mutual exclusion.

### Completed production stage — two-direction mutual exclusion, 2026-09-26

With Minecraft healthy and holding the lock, a controlled ARK start request
exited with code `75` and the exact `GAME SLOT BUSY: another game server is
already running on this node.` message. Minecraft remained running, retained
the lock, and continued listening on both `25565` and `25575`.

For the reverse test, Minecraft was stopped cleanly, ARK was started and
confirmed advertising for join, then a controlled Minecraft start exited with
the same code `75` and message. ARK remained healthy throughout. ARK was then
stopped cleanly and Minecraft restored; it completed NeoForge startup, holds
the lock, has RCON ready on `25575`, and listens on `25565`. The mandatory
two-direction test is complete.

## Rollback

Rollback is always stop-first:

1. Stop Wings Minecraft and confirm `25565`/`25575` are free.
2. Keep the Wings copy; do not delete it while diagnosing.
3. Restore from the verified snapshot only if the preserved source itself was
   changed unexpectedly.
4. Restore the old Compose containers' intended restart policy and start the
   old project from `/srv/docker/minecraft/foreverworld`.
5. Verify the same world and perform an in-game smoke test.

Do not merge changes from the Wings copy back into the source as an emergency
rollback step; that is a separate, reviewed data-reconciliation operation.

## Retirement

Keep the source project and snapshot for an operator-agreed confidence period.
Only then remove the old Foreverworld Portainer stack. The Portainer agent may
remain for read-only host visibility, but Portainer must never own or mutate
Wings-created containers.
