#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
ANSIBLE_DIR="${REPO_ROOT}/terraform/lxc/ansible"
# Per-environment runtime root — non-empty when PVE_ENV is set.
# Generated files (inventory, network vars, edge output) land here when the
# env-scoped Terragrunt layout is in use; falls back to STACKS_DIR otherwise.
ENV_ROOT="${REPO_ROOT}/terraform/lxc/environments/${PVE_ENV:-}"

usage() {
  cat <<'EOF'
Usage: scripts/provision.sh [--tier <platform|apps|all>] [--stack <name>]
                            [--target-env <pve-test-vm|pve>] [--check]

Options:
  --tier        Limit orchestration to a deployment tier (default: all).
  --stack       Run only the named stack (repeatable).
  --target-env  Assert that PVE_ENV matches before running (guards against
                loading secrets for a different environment).
  --check       Run ansible-playbook in check mode (skips smoke tests).
  -h, --help    Show this help text.

Environment selection happens before this script runs via the wrapper:
  PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --tier platform
  ./with-secrets-prod scripts/provision.sh --stack monitoring-stack
EOF
}

log() {
  printf '[provision] %s\n' "$*"
}

fail() {
  printf '[provision] ERROR: %s\n' "$*" >&2
  exit 1
}

expected_pve_host_for_env() {
  # SDN-VLAN-attached stacks deploy a genuinely separate instance per
  # environment (see stack.yaml's `network: zone:`), so their inventory
  # must point at the matching pve_host. Physical/pve-only stacks (no
  # `network:` section, e.g. gaming-stack) have no such guarantee and are
  # deliberately exempt — see assert_inventory_matches_env below.
  case "${PVE_ENV:-}" in
    pve) printf 'pve.gibbsgreatly.xyz' ;;
    pve-test-vm|"") printf 'pve-test-vm.gibbsgreatly.xyz' ;;
    *) printf '' ;;
  esac
}

# Guards against the 2026-07-06 incident class: a stack not yet migrated to
# the per-environment Terragrunt layout falls back to a single, shared
# inventory.yml that silently carries whichever environment's connection
# details Terraform last generated — regardless of the PVE_ENV this run
# actually intends. See docs/dhcp-refactor/decisions.md Decision 5's
# incident note for the concrete case this caught in review.
assert_inventory_matches_env() {
  local stack="$1"
  local inventory_file="$2"
  local stack_yaml="${STACKS_DIR}/${stack}/stack.yaml"

  # Only stacks with an SDN `network:` zone are expected to have a distinct
  # deployment per environment; physical/pve-only stacks are exempt.
  [[ -f "$stack_yaml" ]] || return 0
  grep -q '^network:' "$stack_yaml" || return 0

  local expected_pve_host
  expected_pve_host="$(expected_pve_host_for_env)"
  [[ -n "$expected_pve_host" ]] || return 0

  local actual_pve_host
  actual_pve_host="$(grep -m1 'pve_host:' "$inventory_file" 2>/dev/null | awk '{print $2}')"
  [[ -n "$actual_pve_host" ]] || return 0

  if [[ "$actual_pve_host" != "$expected_pve_host" ]]; then
    fail "${stack}: inventory (${inventory_file}) targets pve_host=${actual_pve_host}, but PVE_ENV=${PVE_ENV:-<unset>} expects ${expected_pve_host}. This stack is likely not yet on the per-environment Terragrunt layout (terraform/lxc/environments/<env>/${stack}/) and its shared inventory is stale from a different environment's last terraform apply. Regenerate the correct inventory before provisioning — do not proceed."
  fi
}

is_truthy() {
  local value
  value="${1,,}"
  case "$value" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

resolve_secrets_file_hint() {
  local pve_env="${PVE_ENV:-}"
  local repo_root
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  # Most per-node secrets are per-node deltas now (see
  # docs/framework-integration/decisions.md Decision 6) — only a handful of
  # keys (the Proxmox token family, TF_VAR_lxc_password) actually live in
  # terraform/secrets.<env>.enc.yaml; everything else is in secrets.common.enc.yaml.
  # This previously only special-cased "pve" and silently fell back to the
  # base file for every other env, including pve-test-vm — generalized here
  # so the hint is correct for any environment with its own delta file.
  if [[ -n "$pve_env" && -f "${repo_root}/terraform/secrets.${pve_env}.enc.yaml" ]]; then
    printf 'terraform/secrets.%s.enc.yaml' "$pve_env"
    return 0
  fi

  printf 'terraform/secrets.common.enc.yaml'
}

ensure_portainer_oauth_secret() {
  local stack="$1"
  local oauth_enabled="${PORTAINER_OAUTH_ENABLED:-true}"
  local edge_manifest="${STACKS_DIR}/portainer-stack/edge.yaml"

  [[ "$stack" == "portainer-stack" ]] || return 0

  if ! is_truthy "$oauth_enabled"; then
    log "Portainer OAuth disabled; skipping OAuth secret bootstrap"
    return 0
  fi

  if [[ -n "${PORTAINER_OAUTH_CLIENT_SECRET:-}" ]]; then
    log "PORTAINER_OAUTH_CLIENT_SECRET is already present"
    return 0
  fi

  [[ -n "${AUTHENTIK_SUPERUSER_API_TOKEN:-}" ]] || fail "PORTAINER_OAUTH_CLIENT_SECRET is missing and cannot be bootstrapped because AUTHENTIK_SUPERUSER_API_TOKEN is unset"
  [[ -f "$edge_manifest" ]] || fail "expected Authentik edge manifest not found: ${edge_manifest}"

  PORTAINER_OAUTH_CLIENT_SECRET="$(openssl rand -hex 32)"
  export PORTAINER_OAUTH_CLIENT_SECRET
  log "Generated PORTAINER_OAUTH_CLIENT_SECRET for this deploy run (in-memory only)"
  log "Persist this secret to $(resolve_secrets_file_hint) after this run for reproducibility"

  [[ -n "${LAB_IP_AUTHENTIK:-}" ]] || fail "LAB_IP_AUTHENTIK is required for Authentik reconcile (inject via with-secrets)"

  log "Reconciling Authentik OIDC provider for Portainer with generated secret"
  python3 "${REPO_ROOT}/terraform/lxc/reconcile-authentik-edge.py" \
    "$edge_manifest" \
    --authentik-url "https://authentik-int.${LAB_DOMAIN:-lab.gibbsgreatly.xyz}:9443" \
    --no-verify-tls \
    --apply \
    --json
}

reconcile_all_edge() {
  local check_mode="$1"
  local stacks_dir="$STACKS_DIR"
  local proxy_playbook="${ANSIBLE_DIR}/playbooks/deploy-proxy-stack.yml"

  local proxy_inventory
  if [[ -f "${ENV_ROOT}/proxy-stack/inventory.yml" ]]; then
    proxy_inventory="${ENV_ROOT}/proxy-stack/inventory.yml"
  else
    proxy_inventory="${stacks_dir}/proxy-stack/inventory.yml"
  fi

  local generated_traefik_dir
  if [[ -n "${PVE_ENV:-}" ]]; then
    generated_traefik_dir="${ENV_ROOT}/.generated/traefik"
  else
    generated_traefik_dir="${REPO_ROOT}/terraform/lxc/.generated/traefik"
  fi

  [[ -f "$proxy_inventory" ]] || { log "SKIP edge reconcile: proxy-stack inventory not found"; return 0; }

  local reconcile_args=(
    python3 "${REPO_ROOT}/terraform/lxc/reconcile-edge.py"
    --stacks-dir "$stacks_dir"
    --authentik-url "https://authentik-int.${LAB_DOMAIN:-lab.gibbsgreatly.xyz}:9443"
    --no-verify-tls
    --json
  )

  if [[ "$check_mode" == "true" ]]; then
    log "Edge reconcile dry-run (all stacks)"
    "${reconcile_args[@]}"
  else
    log "Edge reconcile apply (all stacks)"
    "${reconcile_args[@]}" --apply

    local proxy_extra_vars_file
    proxy_extra_vars_file="$(mktemp "/tmp/proxy-stack.ansible-extra-vars.XXXXXX.yml")"
    render_stack_ansible_extra_vars "proxy-stack" "$proxy_extra_vars_file"

    log "Push generated Traefik config to proxy-stack"
    ansible-playbook -i "$proxy_inventory" -u root "$proxy_playbook" \
      -e "@${proxy_extra_vars_file}" \
      -e "traefik_generated_source_dir=${generated_traefik_dir}"
    rm -f "$proxy_extra_vars_file"
  fi
}

register_portainer_environments() {
  local check_mode="$1"
  local stacks_dir="$STACKS_DIR"
  local playbook="${ANSIBLE_DIR}/playbooks/register-portainer-env.yml"

  local stacks=()
  for stack_yaml in "${stacks_dir}"/*/stack.yaml; do
    if python3 -c "
import yaml, sys
with open(sys.argv[1]) as f: d = yaml.safe_load(f) or {}
sys.exit(0 if d.get('register_portainer_env') else 1)
" "$stack_yaml" 2>/dev/null; then
      stacks+=("$(basename "$(dirname "$stack_yaml")")")
    fi
  done

  if [[ ${#stacks[@]} -eq 0 ]]; then
    log "SKIP portainer env registration: no stacks with register_portainer_env: true"
    return 0
  fi

  # Physical home-LAN stacks (gaming/media/torrent/management) have no
  # per-environment inventory and are only meaningful on pve. On any other
  # environment the controller can still reach them (same LAN) but would
  # register them against the wrong (test) Portainer instance.
  if [[ "${PVE_ENV:-}" != "pve" ]]; then
    log "SKIP portainer env registration: only runs on pve (PVE_ENV=${PVE_ENV:-unset})"
    return 0
  fi

  log "Portainer env registration: ${stacks[*]}"

  for stack in "${stacks[@]}"; do
    local inventory
    if [[ -f "${ENV_ROOT}/${stack}/inventory.yml" ]]; then
      inventory="${ENV_ROOT}/${stack}/inventory.yml"
    else
      inventory="${stacks_dir}/${stack}/inventory.yml"
    fi
    if [[ ! -f "$inventory" ]]; then
      log "SKIP portainer env registration for ${stack}: inventory not found"
      continue
    fi
    if [[ "$check_mode" == "true" ]]; then
      log "  dry-run: would register ${stack}"
    else
      log "  registering ${stack} with Portainer"
      ansible-playbook -i "$inventory" -u root "$playbook"
    fi
  done
}

repair_portainer_migrated_app_stacks() {
  local check_mode="$1"
  local stacks_dir="$STACKS_DIR"
  local repair_stacks=()

  for stack_dir in "${stacks_dir}"/*; do
    [[ -d "$stack_dir" ]] || continue

    local stack
    stack="$(basename "$stack_dir")"

    local inventory
    if [[ -f "${ENV_ROOT}/${stack}/inventory.yml" ]]; then
      inventory="${ENV_ROOT}/${stack}/inventory.yml"
    else
      inventory="${stack_dir}/inventory.yml"
    fi
    [[ -f "$inventory" ]] || continue

    local playbook_name
    playbook_name="$(extract_ansible_playbook "$inventory")"
    if [[ "$playbook_name" == "migrate-portainer-stack" || "$playbook_name" == "migrate-portainer-stack.yml" ]]; then
      repair_stacks+=("$stack")
    fi
  done

  if [[ ${#repair_stacks[@]} -eq 0 ]]; then
    log "SKIP Portainer app endpoint repair: no stacks use migrate-portainer-stack"
    return 0
  fi

  # These are physical home-LAN hosts with no per-environment inventory. The
  # ansible controller (operator's machine) is on that LAN and can reach them
  # regardless of which PVE_ENV is targeted — so the gate must be explicit, not
  # based on network reachability. Only run repair on pve; on pve-test-vm the
  # controller would SSH into the real hosts and register them against the wrong
  # (test) Portainer instance.
  if [[ "${PVE_ENV:-}" != "pve" ]]; then
    log "SKIP Portainer app endpoint repair: only runs on pve (PVE_ENV=${PVE_ENV:-unset})"
    return 0
  fi

  log "Portainer app endpoint repair: ${repair_stacks[*]}"

  if [[ "$check_mode" == "true" ]]; then
    log "  dry-run: standalone portainer-stack recovery would re-pair migrated app endpoints"
    return 0
  fi

  for stack in "${repair_stacks[@]}"; do
    log "  repairing Portainer-managed app stack: ${stack}"
    provision_stack "$stack" "false"
  done
}

layers_include_stack() {
  local stack_name="$1"
  local layers_json="$2"

  python3 -c "
import json, sys
d = json.load(sys.stdin)
target = sys.argv[1]
sys.exit(0 if any(target in layer for layer in d['layers']) else 1)
" "$stack_name" <<<"$layers_json"
}

extract_ansible_playbook() {
  local inventory_file="$1"

  python3 -c "import yaml,sys; inv=yaml.safe_load(sys.stdin); grp=next(iter(inv['all']['children'].values())); host=next(iter(grp['hosts'].values())); print(host.get('ansible_playbook',''))" <"${inventory_file}"
}

render_stack_ansible_extra_vars() {
  local stack="$1"
  local output_file="$2"
  local stack_file="${STACKS_DIR}/${stack}/stack.yaml"

  python3 - "$stack_file" "$output_file" <<'PY'
import os
import re
import sys
import yaml

stack_file = sys.argv[1]
output_file = sys.argv[2]

SOCKET_PROXY_KEYS = (
    "enable_docker_socket_proxy",
    "docker_socket_proxy_bind_addr",
    "docker_socket_proxy_listen_port",
    "docker_socket_proxy_targets",
)

PORTAINER_MIGRATION_KEYS = (
    "portainer_stacks",
    "portainer_migration_legacy_ip",
)

HARBOR_REPULL_KEYS = (
    "harbor_repull_enabled",
)

ES_FINDINGS_INGEST_KEYS = (
    "es_findings_ingest_enabled",
)

GVM_FINDINGS_INGEST_KEYS = (
    "gvm_findings_ingest_enabled",
)

WAZUH_FINDINGS_INGEST_KEYS = (
    "wazuh_findings_ingest_enabled",
)

CVE_ENRICHMENT_SYNC_KEYS = (
    "cve_enrichment_sync_enabled",
)

CVE_DEEP_DIVE_KEYS = (
    "cve_enrichment_sync_deep_dive_enabled",
)


def resolve_placeholders(value):
    if isinstance(value, str):
        def repl(match):
            name = match.group(1)
            # Check uppercase and TF_VAR_ before lowercase — env-specific overrides
            # (LAB_IP_* from .env.pve-test-vm) must win over base lowercase values
            # from SOPS secrets that carry production IPs.
            for candidate in (name.upper(), f"TF_VAR_{name}", name):
                if candidate in os.environ:
                    return os.environ[candidate]
            return match.group(0)

        resolved = value
        for _ in range(5):
            next_value = re.sub(r"\$\{([^}]+)\}", repl, resolved)
            if next_value == resolved:
                break
            resolved = next_value
        return resolved

    if isinstance(value, list):
        return [resolve_placeholders(item) for item in value]

    if isinstance(value, dict):
        return {key: resolve_placeholders(item) for key, item in value.items()}

    return value


def die(message):
    print(f"[provision] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


with open(stack_file, "r", encoding="utf-8") as handle:
    stack = yaml.safe_load(handle) or {}

extra_vars = {}

# Always inject the stack directory so playbooks can reference compose files
extra_vars["stack_dir"] = os.path.dirname(os.path.abspath(stack_file))

for key in SOCKET_PROXY_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

if extra_vars.get("enable_docker_socket_proxy") is True:
    bind_addr = str(extra_vars.get("docker_socket_proxy_bind_addr", ""))
    if not bind_addr:
        die(f"{stack_file}: enabled docker socket proxy requires docker_socket_proxy_bind_addr")
    if "${" in bind_addr:
        die(f"{stack_file}: unresolved docker_socket_proxy_bind_addr placeholder: {bind_addr}")

for key in PORTAINER_MIGRATION_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

for key in HARBOR_REPULL_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

for key in ES_FINDINGS_INGEST_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

for key in GVM_FINDINGS_INGEST_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

for key in WAZUH_FINDINGS_INGEST_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

for key in CVE_ENRICHMENT_SYNC_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

for key in CVE_DEEP_DIVE_KEYS:
    if key in stack and stack[key] is not None:
        extra_vars[key] = resolve_placeholders(stack[key])

with open(output_file, "w", encoding="utf-8") as handle:
    yaml.safe_dump(extra_vars, handle, sort_keys=False)
PY
}

resolve_stack_layers() {
  local tier_filter="$1"
  local explicit_csv="$2"

  python3 - "$STACKS_DIR" "$tier_filter" "$explicit_csv" <<'PY'
import json
import os
import sys
import yaml

stacks_dir = sys.argv[1]
tier_filter = sys.argv[2]
explicit_csv = sys.argv[3]

# Validation guard only — not used for ordering (layers are computed from depends_on)
APPROVED_PLATFORM_STACKS = {
    "apt-cacher-stack",
    "harbor-stack",
    "ci-runner-01",
    "dns-stack",
    "graylog-stack",
    "step-ca-stack",
    "authentik-stack",
    "proxy-stack",
    "monitoring-stack",
    "netbox-stack",
    "portainer-stack",
}


def die(message: str) -> None:
    print(f"[provision] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


stack_meta = {}
for entry in sorted(os.listdir(stacks_dir)):
    stack_dir = os.path.join(stacks_dir, entry)
    if not os.path.isdir(stack_dir):
        continue
    stack_file = os.path.join(stack_dir, "stack.yaml")
    if not os.path.isfile(stack_file):
        continue

    with open(stack_file, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(os.path.expandvars(fh.read())) or {}

    name = data.get("stack_name") or entry
    depends_on = data.get("depends_on") or []
    if isinstance(depends_on, str):
        depends_on = [depends_on]
    if not isinstance(depends_on, list):
        die(f"{name}: depends_on must be a list or string")

    stack_meta[name] = {
        "tier": data.get("deployment_tier"),
        "depends_on": [dep for dep in depends_on if isinstance(dep, str) and dep],
        "enabled": bool(data.get("enabled", True)),
    }

if not stack_meta:
    die("no stacks with stack.yaml found under terraform/lxc/stacks")

requested = [s for s in explicit_csv.split(",") if s] if explicit_csv else []

if requested:
    unknown = [s for s in requested if s not in stack_meta]
    if unknown:
        die(f"unknown --stack value(s): {', '.join(unknown)}")
    disabled = [s for s in requested if not stack_meta[s]["enabled"]]
    if disabled:
        die(f"requested stack(s) are disabled in metadata: {', '.join(disabled)}")
    candidates = list(dict.fromkeys(requested))
else:
    if tier_filter not in {"platform", "apps", "all"}:
        die(f"unsupported tier filter: {tier_filter}")

    candidates = []
    for name, meta in sorted(stack_meta.items()):
        if not meta["enabled"]:
            continue
        tier = meta["tier"]
        if tier_filter == "all":
            if tier in {"platform", "apps"}:
                candidates.append(name)
        elif tier == tier_filter:
            candidates.append(name)

if not candidates:
    die("no stacks selected after applying filters")

# Restrict dependency edges to selected candidates only
deps_map = {
    name: [dep for dep in stack_meta[name]["depends_on"] if dep in set(candidates)]
    for name in candidates
}

platform = [name for name in candidates if stack_meta[name]["tier"] == "platform"]

if not requested and tier_filter in {"platform", "all"}:
    extra = sorted(name for name in platform if name not in APPROVED_PLATFORM_STACKS)
    missing = sorted(s for s in APPROVED_PLATFORM_STACKS if s not in set(platform))
    if missing or extra:
        details = []
        if missing:
            details.append("missing=" + ", ".join(missing))
        if extra:
            details.append("extra=" + ", ".join(extra))
        die("platform stacks do not match approved set: " + " ; ".join(details))


def compute_layers(nodes, deps):
    """Kahn's algorithm — returns ordered list of parallel layers."""
    in_degree = {n: 0 for n in nodes}
    children = {n: [] for n in nodes}
    for node in nodes:
        for dep in deps.get(node, []):
            if dep in in_degree:
                in_degree[node] += 1
                children[dep].append(node)

    layers = []
    remaining = set(nodes)
    while remaining:
        layer = sorted(n for n in remaining if in_degree[n] == 0)
        if not layer:
            die("dependency cycle among selected stacks: " + ", ".join(sorted(remaining)))
        layers.append(layer)
        for node in layer:
            remaining.remove(node)
            for child in children[node]:
                in_degree[child] -= 1
    return layers


def compute_rdeps(nodes, deps):
    """Reverse dependency map: rdeps[A] = list of stacks that depend on A."""
    rdeps = {n: [] for n in nodes}
    for node in nodes:
        for dep in deps.get(node, []):
            if dep in rdeps:
                rdeps[dep].append(node)
    return rdeps


layers = compute_layers(candidates, deps_map)
rdeps = compute_rdeps(candidates, deps_map)

print(json.dumps({"layers": layers, "rdeps": rdeps}))
PY
}

provision_stack() {
  local stack="$1"
  local check_mode="$2"
  local inventory_file
  if [[ -f "${ENV_ROOT}/${stack}/inventory.yml" ]]; then
    inventory_file="${ENV_ROOT}/${stack}/inventory.yml"
  else
    inventory_file="${STACKS_DIR}/${stack}/inventory.yml"
  fi

  ensure_portainer_oauth_secret "$stack"

  # dns-stack (CoreDNS) is frozen/rollback-only post-Technitium-cutover
  # (docs/dns-refactor/plan.md Phase 6a). It stays deployed and answering
  # queries as a manual rollback target, but is no longer part of the
  # routine provisioning/reconciliation path -- no automatic zone
  # regeneration, no automatic redeploy.
  if [[ "$stack" == "dns-stack" ]]; then
    log "SKIP ${stack}: frozen/rollback-only since the Technitium cutover (docs/dns-refactor/plan.md Phase 6a) -- no longer part of the routine provisioning path. Deploy manually via ansible-playbook if you specifically need to touch the rollback container."
    return 0
  fi

  if [[ ! -f "$inventory_file" ]]; then
    log "SKIP ${stack}: inventory file not found (${inventory_file})"
    return 0
  fi

  assert_inventory_matches_env "$stack" "$inventory_file"

  local playbook_name
  playbook_name="$(extract_ansible_playbook "$inventory_file")"
  if [[ -z "$playbook_name" ]]; then
    log "SKIP ${stack}: no ansible_playbook in inventory"
    return 0
  fi

  local playbook_file
  if [[ "$playbook_name" == *.yml ]]; then
    playbook_file="${ANSIBLE_DIR}/playbooks/${playbook_name}"
  else
    playbook_file="${ANSIBLE_DIR}/playbooks/${playbook_name}.yml"
  fi
  [[ -f "$playbook_file" ]] || fail "${stack}: playbook file not found (${playbook_file})"

  local extra_vars_file
  extra_vars_file="$(mktemp "/tmp/${stack}.ansible-extra-vars.XXXXXX.yml")"
  render_stack_ansible_extra_vars "$stack" "$extra_vars_file"

  local cmd=(ansible-playbook -i "$inventory_file" "$playbook_file" -e "@${extra_vars_file}")

  # Graylog runtime is validated (pve-test-vm G0-G5, full teardown cycle) and
  # is always deployed for real now, on every environment.
  if [[ "$stack" == "graylog-stack" ]]; then
    cmd=(env GRAYLOG_DEPLOY_RUNTIME=true "${cmd[@]}")
  fi

  # Opt-in only: GitHub deletes a runner's registration after enough idle
  # time (or certain server-side events), independent of whether the LXC
  # itself is up. When that happens the runner service starts and exits
  # immediately (see runsvc.sh's "registration has been deleted" error) --
  # a plain restart never fixes it, it needs actual re-registration.
  if [[ "$stack" == "ci-runner-01" && "${RUNNER_FORCE_RECONFIGURE:-false}" == "true" ]]; then
    log "ci-runner-01: forcing runner de-registration + re-registration (RUNNER_FORCE_RECONFIGURE=true)"
    cmd+=(-e "runner_force_reconfigure=true")
  fi

  if [[ "$stack" == "technitium-stack" ]]; then
    local generated_records
    if [[ -n "${PVE_ENV:-}" ]]; then
      generated_records="${ENV_ROOT}/.generated/technitium/zone-records.json"
    else
      generated_records="${REPO_ROOT}/terraform/lxc/.generated/technitium/zone-records.json"
    fi
    mkdir -p "$(dirname "$generated_records")"
    log "Regenerating Technitium parity-zone records from EdgeManifests"
    python3 "${REPO_ROOT}/terraform/lxc/render-edge-technitium.py" \
      --stacks-dir "${REPO_ROOT}/terraform/lxc/stacks" \
      --seed-zone "${REPO_ROOT}/terraform/lxc/ansible/files/coredns-lab.zone" \
      --output-records "$generated_records"
    cmd+=(-e "technitium_generated_zone_src=${generated_records}")
  fi

  [[ "$check_mode" == "true" ]] && cmd+=(--check)
  [[ -n "${ANSIBLE_TAGS:-}" ]] && cmd+=(--tags "$ANSIBLE_TAGS")

  log "RUN ${stack}: ${cmd[*]}"
  if ! "${cmd[@]}"; then
    rm -f "$extra_vars_file"
    return 1
  fi
  rm -f "$extra_vars_file"

  # H-1d: run per-stack smoke test if present (skipped in check mode)
  if [[ "$check_mode" != "true" ]]; then
    local smoke_script="${STACKS_DIR}/${stack}/smoke-test.sh"
    if [[ -x "$smoke_script" ]]; then
      log "Running smoke test for ${stack}"
      if ! REPO_ROOT="$REPO_ROOT" timeout 180 "$smoke_script"; then
        fail "Smoke test failed for ${stack}"
      fi
      log "Smoke test passed: ${stack}"
    fi
  fi
}

# H-1a: report which downstream stacks are blocked by a failed stack
report_blocked() {
  local failed_stack="$1"
  local layers_json="$2"

  log "ERROR: Stack '${failed_stack}' failed"

  local blocked
  blocked="$(echo "$layers_json" | python3 -c "
import json, sys, collections
d = json.load(sys.stdin)
rdeps = d['rdeps']
failed = sys.argv[1]
seen = set()
queue = collections.deque(rdeps.get(failed, []))
while queue:
    node = queue.popleft()
    if node not in seen:
        seen.add(node)
        queue.extend(rdeps.get(node, []))
if seen:
    print(' '.join(sorted(seen)))
" "$failed_stack")"

  if [[ -n "$blocked" ]]; then
    log "Skipping downstream stacks (depend on ${failed_stack}): ${blocked}"
  fi
}

# --- Argument parsing ---

tier_filter="all"
check_mode=false
target_env=""
declare -a requested_stacks=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier)
      [[ $# -ge 2 ]] || fail "--tier requires a value"
      tier_filter="$2"
      shift 2
      ;;
    --stack)
      [[ $# -ge 2 ]] || fail "--stack requires a value"
      requested_stacks+=("$2")
      shift 2
      ;;
    --target-env)
      [[ $# -ge 2 ]] || fail "--target-env requires a value"
      target_env="$2"
      shift 2
      ;;
    --check)
      check_mode=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

case "$tier_filter" in
  platform|apps|all)
    ;;
  *)
    fail "--tier must be one of: platform, apps, all"
    ;;
esac

explicit_csv=""
if (( ${#requested_stacks[@]} > 0 )); then
  explicit_csv="$(IFS=,; echo "${requested_stacks[*]}")"
fi

# H-1b: environment guard — assert PVE_ENV matches --target-env if provided;
# always emit the resolved target so it appears in every run log.
current_pve_env="${PVE_ENV:-}"
current_proxmox_node="${TF_VAR_proxmox_node:-}"
if [[ -n "$target_env" && "$target_env" != "$current_pve_env" ]]; then
  fail "--target-env ${target_env} does not match PVE_ENV=${current_pve_env:-<unset>}; re-run with the correct wrapper"
fi
log "target: ${current_pve_env:-<unset>} (proxmox_node=${current_proxmox_node:-<unset>})"

# Compute dependency-ordered layers from stack metadata
layers_json="$(resolve_stack_layers "$tier_filter" "$explicit_csv")"
num_layers="$(echo "$layers_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['layers']))")"
(( num_layers > 0 )) || fail "no stacks resolved for execution"

export ANSIBLE_HOST_KEY_CHECKING="False"
export ANSIBLE_CONFIG="${ANSIBLE_DIR}/ansible.cfg"
export ANSIBLE_ROLES_PATH="${ANSIBLE_DIR}/roles"
export ANSIBLE_LOCAL_TEMP="/tmp/.ansible/tmp"
export ANSIBLE_SSH_CONTROL_PATH_DIR="/tmp/.ansible/cp"

# H-1c: execute layers; stacks within each layer run in parallel
for ((i = 0; i < num_layers; i++)); do
  mapfile -t layer_stacks < <(echo "$layers_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for s in d['layers'][int(sys.argv[1])]: print(s)
" "$i")

  (( ${#layer_stacks[@]} > 0 )) || continue
  log "Layer $((i + 1))/${num_layers}: ${layer_stacks[*]}"

  if (( ${#layer_stacks[@]} == 1 )); then
    # Single stack in layer — run directly; no subshell overhead needed
    if ! provision_stack "${layer_stacks[0]}" "$check_mode"; then
      report_blocked "${layer_stacks[0]}" "$layers_json"
      exit 1
    fi
  else
    # Multiple stacks in layer — run in parallel; capture exit via status files
    status_dir="$(mktemp -d "/tmp/provision-layer-$$.XXXXXX")"
    declare -a layer_pids=()
    declare -a pid_stacks=()

    for stack in "${layer_stacks[@]}"; do
      (
        if provision_stack "$stack" "$check_mode" 2>&1 | sed -u "s/^/[${stack}] /"; then
          printf '0' > "${status_dir}/${stack}.exit"
        else
          printf '1' > "${status_dir}/${stack}.exit"
        fi
      ) &
      layer_pids+=("$!")
      pid_stacks+=("$stack")
    done

    layer_failed=false
    declare -a failed_in_layer=()
    for ((j = 0; j < ${#layer_pids[@]}; j++)); do
      wait "${layer_pids[$j]}" || true
      exit_code="$(cat "${status_dir}/${pid_stacks[$j]}.exit" 2>/dev/null || echo '1')"
      if [[ "$exit_code" != "0" ]]; then
        layer_failed=true
        failed_in_layer+=("${pid_stacks[$j]}")
      fi
    done

    rm -rf "$status_dir"
    unset layer_pids pid_stacks

    if [[ "$layer_failed" == true ]]; then
      for failed_stack in "${failed_in_layer[@]}"; do
        report_blocked "$failed_stack" "$layers_json"
      done
      exit 1
    fi
    unset failed_in_layer
  fi
done

if [[ -z "$explicit_csv" ]]; then
  reconcile_all_edge "$check_mode"
  register_portainer_environments "$check_mode"
else
  log "SKIP edge reconcile: single-stack mode (activate-edge phase handles this)"
fi

if layers_include_stack "portainer-stack" "$layers_json"; then
  repair_portainer_migrated_app_stacks "$check_mode"
fi

log "Completed provision orchestration"
