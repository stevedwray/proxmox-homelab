# Portainer Management Follow-Up Notes

## Purpose

This directory tracks Portainer-management work that was discovered while
developing the Docker socket proxy and NetBox runtime discovery path.

This is intentionally separate from the Docker socket proxy workstream. The
socket proxy work is about inspecting Docker runtime state and getting that
data into NetBox. This Portainer note is about portability of Portainer-managed
environments across Portainer instances.

## Discovered Follow-Up Work

### Portainer environment portability

We need a repeatable way to move Portainer-managed environments:

- from the old Portainer instance to the new Portainer instance
- from one rebuilt new Portainer instance to another new Portainer instance

This is not a disaster-recovery problem. Proxmox Backup Server covers the deep
recovery story. The practical requirement here is migration and rebuild
survivability during intentional development, teardown, and redeploy work.

### Likely shape of the future solution

The likely direction is:

- use Portainer backup/restore for full-instance recovery if needed
- use an explicit API-driven export/import or replay workflow for environment
  migration portability

The API-driven path is the one that matters most for planned migration and
teardown-test continuity. It should be treated as a separate workstream from
the Docker socket proxy methodology.

## Not In Scope Here

This note does not define the migration script or perform the migration.

It only records that this branch of work exists and should be handled as a
dedicated Portainer-management task later.
