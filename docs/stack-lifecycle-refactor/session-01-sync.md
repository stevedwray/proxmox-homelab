Session 01: Sync runtime reconcile -> repo

Summary:
- Applied Authentik provider updates for harbor, grafana (monitoring), and portainer during executor session-01.
- Added rendered CoreDNS zone from session as a generated artifact.

Repo changes made by automated refactor step:
- Annotated edge manifests with expected OIDC client env var names:
  - terraform/lxc/stacks/harbor-stack/edge.yaml
  - terraform/lxc/stacks/monitoring-stack/edge.yaml
  - terraform/lxc/stacks/portainer-stack/edge.yaml
- Added rendered CoreDNS zone: terraform/lxc/.generated/coredns/session-01.coredns.zone

Rationale:
- Annotations make the expected Authentik OIDC env var names explicit in the manifest for future automation and discovery.
- Generated CoreDNS zone is stored to make the rendered output part of the repository artifacts for traceability.

No behavioral changes to deployment; these are repo-facing documentation and generated artifacts to keep code and runtime observations aligned.
