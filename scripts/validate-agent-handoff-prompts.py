#!/usr/bin/env python3

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
PLANNER_AGENT = REPO_ROOT / ".github/agents/planner.agent.md"
EXECUTOR_AGENT = REPO_ROOT / ".github/agents/executor.agent.md"
ARCHITECT_AGENT = REPO_ROOT / ".github/agents/architect.agent.md"

CHECKS = {
    "planner": [
        ".git/ai/plan-state.yaml",
        ".git/ai/current-step.spec.yaml",
        "python3 scripts/render-current-step.py",
        "python3 scripts/validate-current-step.py",
        "python3 scripts/validate-plan-state.py",
    ],
    "executor": [
        ".git/ai/current-step.yaml",
        "python3 scripts/validate-current-step.py .git/ai/current-step.yaml",
        "python3 scripts/update-plan-state.py .git/ai/plan-state.yaml <step-id> in_progress",
        ".git/ai/blocker.yaml",
        "python3 scripts/validate-blocker.py .git/ai/blocker.yaml",
    ],
    "architect": [
        ".git/ai/blocker.yaml",
        ".git/ai/current-step.spec.yaml",
        "python3 scripts/render-current-step.py .git/ai/current-step.spec.yaml .git/ai/current-step.yaml",
        "python3 scripts/validate-current-step.py .git/ai/current-step.yaml",
        "Do not depend on `.git/ai/handoff-to-architect.yaml`.",
    ],
}


def check_file(name: str, path: Path, snippets: list[str]) -> list[str]:
    content = path.read_text(encoding="utf-8")
    return [f"{name}:{snippet}" for snippet in snippets if snippet not in content]


def main() -> int:
    missing = []
    missing.extend(check_file("planner", PLANNER_AGENT, CHECKS["planner"]))
    missing.extend(check_file("executor", EXECUTOR_AGENT, CHECKS["executor"]))
    missing.extend(check_file("architect", ARCHITECT_AGENT, CHECKS["architect"]))

    if missing:
        print("FAIL: autonomous workflow safeguards missing")
        for item in missing:
            print(f"- {item}")
        return 1

    print("PASS: autonomous workflow safeguards present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
