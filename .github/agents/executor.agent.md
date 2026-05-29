# Executor agent safeguards

This agent must include references used by the executor safeguards and checks.

- .git/ai/current-step.yaml
- python3 scripts/validate-current-step.py .git/ai/current-step.yaml
- python3 scripts/update-plan-state.py .git/ai/plan-state.yaml <step-id> in_progress
- .git/ai/blocker.yaml
- python3 scripts/validate-blocker.py .git/ai/blocker.yaml
