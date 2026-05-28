# Architect agent safeguards

This agent must include references used by the architect safeguards and checks.

- .git/ai/blocker.yaml
- .git/ai/current-step.spec.yaml
- python3 scripts/render-current-step.py .git/ai/current-step.spec.yaml .git/ai/current-step.yaml
- python3 scripts/validate-current-step.py .git/ai/current-step.yaml
- Do not depend on `.git/ai/handoff-to-architect.yaml`.
