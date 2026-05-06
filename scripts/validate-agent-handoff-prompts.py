#!/usr/bin/env python3

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHITECT_AGENT = REPO_ROOT / ".github/agents/architect.agent.md"

REQUIRED_SNIPPETS = [
    "overwrite any existing\nfile completely",
    "Do not reuse, append to, or partially edit a prior session\nhandoff",
    "scripts/teardown-deploy-test.sh",
    "include both `--execute`\n  and `--approval-text \"<operator-approved text>\"`",
    "Do not omit `deploy-edge`",
    ".git/ai/sessions/evidence/<session-id>/<gate-id>.log",
]

PHASE_SEQUENCE = [
    "`destroy`",
    "`deploy-foundation`",
    "`deploy-edge`",
    "`activate-edge`",
    "`deploy-platform`",
    "`final-validation`",
]


def main() -> int:
    content = ARCHITECT_AGENT.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in content]

    sequence_positions = []
    search_start = 0
    for phase in PHASE_SEQUENCE:
        position = content.find(phase, search_start)
        if position == -1:
            missing.append(f"phase-sequence:{phase}")
            continue
        sequence_positions.append((phase, position))
        search_start = position + len(phase)

    if missing:
        print("FAIL: architect handoff safeguards missing")
        for item in missing:
            print(f"- {item}")
        return 1

    print("PASS: architect handoff safeguards present")
    for phase, position in sequence_positions:
        print(f"- {phase} @ {position}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
