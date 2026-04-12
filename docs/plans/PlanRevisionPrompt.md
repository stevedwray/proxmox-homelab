# Session Prompt — Plan Revision

You are working in the proxmox-homelab repository at `/home/steve/git/proxmox-homelab`.

## What this session does

This is a **planning and documentation session only**. You will revise the build plan
documents to reflect decisions made in a prior review session. You will not run
Terraform, Ansible, or any deployment commands. You will not write application code.

## Start here

Read `docs/plans/PlanRevisionBrief.md` in full before doing anything else.

That document contains:
- The full list of documents you need to read before making changes
- Nine numbered changes to execute, in order
- Constraints on what you may and may not do

## The most important change

Change 1 (SDN zone design) must be done before all others because the task file
updates in Changes 4, 7, and 9 depend on having concrete zone names, subnets, and
container placements to reference.

Every container that gets deployed in Phase 04 and Phase 05 must have a named SDN
zone, a justified IP address, and a documented cross-zone routing intent before its
task file is written or updated. This is not optional and not deferrable.

## When you are done

Report back with:
- A list of every file changed or created, with one line saying what changed
- The three `gh issue close` commands for #89, #104, and #111 (show the commands;
  ask before running them)
- Any decisions you made during Change 1 (zone design) that had more than one
  reasonable option, so they can be reviewed
