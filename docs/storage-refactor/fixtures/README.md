This fixtures directory contains lightweight classifier test vectors only.

Do NOT treat these files as authoritative Phase 0 evidence.

Authoritative Phase 0 evidence must come from provider-backed `terragrunt plan`
/ `terraform show -json` output captured from the `test-storage` stack and stored
outside of tracked `docs/` paths (for example, ephemeral `/tmp` artifacts or
CI-attached build artifacts). Fixtures here are small repeatable inputs for the
classifier unit testing and developer experimentation only.
