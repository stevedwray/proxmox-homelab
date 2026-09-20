# pterodactyl-lab — Stack Contract

## Purpose

Pterodactyl Panel — the web UI/API/database for controlling
`gaming-stack-lab`'s game servers (Minecraft, ARK: Survival Ascended,
future AzerothCore) without driving Portainer's UI by hand. This stack is
Panel only. Wings, the daemon that actually starts/stops each game's
Docker container, runs on `gaming-stack-lab` itself — Wings requires
direct access to the Docker daemon it manages and has no supported way to
control a remote host's Docker. See `docs/gaming-stack-lab/plan.md` for
the full research and decision trail.

## Network

| Field   | Value                          |
|---------|--------------------------------|
| Zone    | `game_seg` (VLAN 60)           |
| IP      | `192.168.60.20/24`             |
| Gateway | `192.168.60.1`                 |
| VMID    | 60020                          |

## Inputs

| Secret                          | Purpose                                  |
|----------------------------------|-------------------------------------------|
| `PTERODACTYL_LAB_DB_PASSWORD`     | MariaDB `pterodactyl` user password       |
| `PTERODACTYL_LAB_DB_ROOT_PASSWORD`| MariaDB root password                     |

Not yet added to `terraform/secrets.common.enc.yaml` — required before
first real deploy, tracked in `docs/gaming-stack-lab/plan.md`'s open
questions.

## Provides

| Service            | Port | Protocol | Notes                      |
|---------------------|------|----------|-----------------------------|
| pterodactyl-panel   | 80   | HTTP     | Fronted by Traefik (TLS termination happens there, not in this container) |

`stack.yaml` service identifier: `pterodactyl-panel`.

## Dependencies

None at first deploy. Wings on `gaming-stack-lab` will depend on this
stack once paired (node token, generated in Panel's own admin UI) — not
yet a scripted step, see `docs/gaming-stack-lab/plan.md`'s open questions.

## Persistent State

| Path                       | Storage                     | Contents                          |
|-----------------------------|------------------------------|-------------------------------------|
| `pterodactyl-db` volume     | `docker_storage` (10 GiB)    | MariaDB data — Panel's own DB, not game data |
| `pterodactyl-var` volume    | `docker_storage`             | Panel app state                     |
| `pterodactyl-nginx` volume  | `docker_storage`             | Panel's internal nginx config       |
| `pterodactyl-logs` volume   | `docker_storage`             | Panel application logs              |

Game server data itself (world saves, ARK installs, etc.) lives on
`gaming-stack-lab`'s own `/srv/docker` mount, not here — this stack never
holds game data.

## What May Depend on This Stack

Wings, once installed on `gaming-stack-lab` and paired (future work, not
yet scripted).

## What Must Not Be Edited Casually

- `APP_URL` must match whatever hostname Traefik's `edge.yaml` routes to
  this stack — Panel signs/validates redirects against it.
- Panel's DB (`pterodactyl-db`) holds every game server's Wings
  configuration once paired — never delete this volume without a backup;
  it is not game-server data itself but losing it breaks every managed
  server's Panel-side record.

## Playbook

`deploy-pterodactyl-lab`
