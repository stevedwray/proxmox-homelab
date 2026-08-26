# smoketest-stack — Stack Contract

## Purpose

Disposable smoke-test stack validating the LXC-provision-then-Ansible-configure
pipeline for the agent-design methodology. Not a real service -- safe to
destroy at any point. A single nginx container serving its own default
welcome page, nothing else.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | plain LAN bridge (vmbr0) |
| IP           | 192.168.1.99/24          |
| Gateway      | 192.168.1.1              |
| VMID         | 99010                    |

## Inputs

*No inputs beyond platform defaults.*

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| http    | 80   | tcp      | nginx default welcome page, no custom content |

## Dependencies

None.

## Persistent State

*No persistent state.*

## What May Depend On This Stack

Nothing depends on this stack.

## What Must Not Be Edited Casually

Nothing -- this stack is fully disposable and carries no shared state or
downstream consumers.
