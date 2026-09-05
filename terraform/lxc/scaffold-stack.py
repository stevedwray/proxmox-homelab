#!/usr/bin/env python3
"""Scaffold a new stack's five files -- DEPRECATED automation, do not run.

**opencode is a deprecated path in this lab (operator decision, 2026-09-04
-- see docs/media-stack-lab/plan.md).** This script drove five narrow-scoped
OpenCode agents (one per generated file, gated by real validators between
steps) and is left in place only as a reference for that design, not as a
runnable tool. `main()` refuses to run for that reason.

Do this instead, the same way `docs/media-stack-lab/plan.md` records doing
it: author the five files by hand from `stack-request.yaml`'s fields
(`stack_yaml`, `compose_requirements`/`compose_forbidden`, `contract_facts`,
`playbook_content`), modeled on an existing stack's real files for shape,
then run the same validators this script would have run between steps:
    validate-stack-metadata.sh
    validate-compose.sh --stack <name>
    validate-stack-metadata.sh --check-contract-sections
    ansible-playbook --syntax-check <playbook>

Original usage (kept for context, no longer supported):
    terraform/lxc/scaffold-stack.sh <stack-name>

Reads terraform/lxc/stacks/<stack-name>/stack-request.yaml (human-authored,
not part of the stack's final file set) and would have driven, in order:
    stack-yaml-writer -> validate-stack-metadata.sh
    compose-writer    -> validate-compose.sh
    contract-writer   -> validate-stack-metadata.sh --check-contract-sections
    terragrunt-writer -> (no validator; content is fixed boilerplate)
    playbook-writer   -> ansible-playbook --syntax-check
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

OPENCODE_MODEL = "ollama_lan/eval-qwen3-coder-30b-a3b:q4_k_m"


def main() -> int:
    die(
        "scaffold-stack.py is deprecated: it drives opencode, which is a "
        "deprecated path in this lab (operator decision, 2026-09-04 -- see "
        "docs/media-stack-lab/plan.md). Author the five stack files by hand "
        "from stack-request.yaml instead, then run the same validators this "
        "script would have (see the module docstring for the exact list)."
    )
    return 1  # unreachable -- die() above calls sys.exit(1)


def _scaffold_via_opencode(args: argparse.Namespace) -> int:
    """Original opencode-driven implementation, kept only as a design
    reference (see the module docstring) -- not called from main() anymore.
    """
    repo_root = Path(__file__).resolve().parents[2]
    lxc_dir = repo_root / "terraform" / "lxc"
    stack_dir = lxc_dir / "stacks" / args.stack_name
    request_path = stack_dir / "stack-request.yaml"

    if not request_path.exists():
        die(
            f"missing {request_path} — author it first (see "
            "terraform/lxc/stacks/stack-request.example.yaml for the shape)"
        )

    request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    stack_yaml_fields = request["stack_yaml"]
    if stack_yaml_fields.get("hostname") != args.stack_name:
        die(
            f"stack_yaml.hostname ({stack_yaml_fields.get('hostname')!r}) "
            f"must match the stack name ({args.stack_name!r})"
        )

    print(f"== Scaffolding '{args.stack_name}' ==\n")

    run_stack_yaml_writer(repo_root, stack_dir, stack_yaml_fields)
    run_validator(repo_root, ["terraform/lxc/validate-stack-metadata.sh"])

    run_compose_writer(repo_root, stack_dir, request)
    run_validator(
        repo_root,
        ["terraform/lxc/validate-compose.sh", "--stack", args.stack_name],
    )

    run_contract_writer(repo_root, stack_dir, args.stack_name, request)
    run_validator(
        repo_root,
        [
            "terraform/lxc/validate-stack-metadata.sh",
            "--check-contract-sections",
        ],
    )

    run_terragrunt_writer(repo_root, stack_dir)

    playbook_path = (
        lxc_dir
        / "ansible"
        / "playbooks"
        / f"{stack_yaml_fields['ansible_playbook']}.yml"
    )
    run_playbook_writer(repo_root, playbook_path, request["playbook_content"])
    run_syntax_check(repo_root, playbook_path)

    print(f"\n== '{args.stack_name}' scaffolded and validated cleanly ==")
    print(
        "Not yet run: terragrunt plan/apply, provision.sh check/live/rerun, "
        "health check — those are real infrastructure steps, run them "
        "yourself."
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stack_name")
    return parser.parse_args()


def die(message: str) -> None:
    print(f"[scaffold-stack] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def run_agent(repo_root: Path, agent: str, message: str) -> None:
    print(f"-- {agent} --")
    result = subprocess.run(
        [
            "opencode",
            "run",
            message,
            "--agent",
            agent,
            "-m",
            OPENCODE_MODEL,
            "--dir",
            str(repo_root),
            "--auto",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        die(f"{agent} exited {result.returncode}")


def run_validator(repo_root: Path, command: list[str]) -> None:
    result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        die(f"validator failed: {' '.join(command)}")
    print()


def run_syntax_check(repo_root: Path, playbook_path: Path) -> None:
    result = subprocess.run(
        [
            "ansible-playbook",
            "--syntax-check",
            "-i",
            "localhost,",
            "-c",
            "local",
            str(playbook_path.relative_to(repo_root)),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={
            "HOME": tempfile.mkdtemp(prefix="scaffold-stack-ansible-home-"),
            "ANSIBLE_ROLES_PATH": str(repo_root / "terraform/lxc/ansible/roles"),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        die("ansible-playbook --syntax-check failed")
    print()


def run_stack_yaml_writer(repo_root: Path, stack_dir: Path, fields: dict) -> None:
    target = stack_dir.relative_to(repo_root) / "stack.yaml"
    content = yaml.dump(fields, sort_keys=False, default_flow_style=False)
    message = f"Write this exact content to {target}:\n\n{content}"
    run_agent(repo_root, "stack-yaml-writer", message)


def run_compose_writer(repo_root: Path, stack_dir: Path, request: dict) -> None:
    target = stack_dir.relative_to(repo_root) / "docker-compose.yml"
    message = (
        f"Author {target} to these requirements:\n\n"
        f"{request['compose_requirements'].strip()}\n\n"
        f"Do not add: {request['compose_forbidden'].strip()}"
    )
    run_agent(repo_root, "compose-writer", message)


def run_contract_writer(
    repo_root: Path, stack_dir: Path, stack_name: str, request: dict
) -> None:
    target = stack_dir.relative_to(repo_root) / "STACK_CONTRACT.md"
    message = (
        f"Write {target} for the {stack_name} stack. Stack facts:\n\n"
        f"{request['contract_facts'].strip()}"
    )
    run_agent(repo_root, "contract-writer", message)


def run_terragrunt_writer(repo_root: Path, stack_dir: Path) -> None:
    target = stack_dir.relative_to(repo_root) / "terragrunt.hcl"
    message = f"Write terragrunt.hcl to {target}."
    run_agent(repo_root, "terragrunt-writer", message)


def run_playbook_writer(repo_root: Path, playbook_path: Path, content: str) -> None:
    target = playbook_path.relative_to(repo_root)
    message = f"Write this exact content to {target}:\n\n{content.strip()}"
    run_agent(repo_root, "playbook-writer", message)


if __name__ == "__main__":
    raise SystemExit(main())
