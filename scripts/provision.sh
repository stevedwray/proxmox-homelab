#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
ANSIBLE_DIR="${REPO_ROOT}/terraform/lxc/ansible"

usage() {
  cat <<'EOF'
Usage: scripts/provision.sh [--tier <platform|apps|all>] [--stack <name>] [--check]

Options:
  --tier   Limit orchestration to a deployment tier (default: all).
  --stack  Run only the named stack (repeatable).
  --check  Run ansible-playbook in check mode.
  -h, --help  Show this help text.
EOF
}

log() {
  printf '[provision] %s\n' "$*"
}

fail() {
  printf '[provision] ERROR: %s\n' "$*" >&2
  exit 1
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
  local proxmox_node="${TF_VAR_proxmox_node:-}"

  if [[ "$pve_env" == "pve" || "$proxmox_node" == "pve" ]]; then
    printf 'terraform/secrets.pve.enc.yaml'
    return 0
  fi

  printf 'terraform/secrets.enc.yaml'
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

ensure_portainer_edge_publish() {
  local stack="$1"
  local check_mode="$2"
  local edge_manifest="${STACKS_DIR}/portainer-stack/edge.yaml"
  local proxy_inventory="${STACKS_DIR}/proxy-stack/inventory.yml"
  local proxy_playbook="${ANSIBLE_DIR}/playbooks/deploy-proxy-stack.yml"
  local generated_traefik_dir="${REPO_ROOT}/terraform/lxc/.generated/traefik"

  [[ "$stack" == "portainer-stack" ]] || return 0

  [[ -f "$edge_manifest" ]] || fail "expected edge manifest not found: ${edge_manifest}"
  [[ -f "$proxy_inventory" ]] || fail "expected proxy inventory not found: ${proxy_inventory}"
  [[ -f "$proxy_playbook" ]] || fail "expected proxy playbook not found: ${proxy_playbook}"

  [[ -n "${LAB_IP_AUTHENTIK:-}" ]] || fail "LAB_IP_AUTHENTIK is required for Authentik reconcile (inject via with-secrets)"

  if [[ "$check_mode" == "true" ]]; then
    log "Reconcile edge dry-run for Portainer route publication"
    python3 "${REPO_ROOT}/terraform/lxc/reconcile-edge.py" \
      "$edge_manifest" \
      --authentik-url "https://authentik-int.${LAB_DOMAIN:-lab.gibbsgreatly.xyz}:9443" \
      --no-verify-tls \
      --json
  else
    log "Reconcile edge apply for Portainer route publication"
    python3 "${REPO_ROOT}/terraform/lxc/reconcile-edge.py" \
      "$edge_manifest" \
      --authentik-url "https://authentik-int.${LAB_DOMAIN:-lab.gibbsgreatly.xyz}:9443" \
      --no-verify-tls \
      --apply \
      --json

    log "Publish generated Traefik files for Portainer route"
    ansible-playbook -i "$proxy_inventory" -u root "$proxy_playbook" \
      -e "traefik_generated_source_dir=${generated_traefik_dir}"
  fi
}

extract_ansible_playbook() {
  local inventory_file="$1"

  python3 -c "import yaml,sys; inv=yaml.safe_load(sys.stdin); grp=next(iter(inv['all']['children'].values())); host=next(iter(grp['hosts'].values())); print(host.get('ansible_playbook',''))" <"${inventory_file}"
}

resolve_stack_order() {
  local tier_filter="$1"
  local explicit_csv="$2"

  python3 - "$STACKS_DIR" "$tier_filter" "$explicit_csv" <<'PY'
import os
import sys
import yaml

stacks_dir = sys.argv[1]
tier_filter = sys.argv[2]
explicit_csv = sys.argv[3]

APPROVED_PLATFORM_ORDER = [
    "apt-cacher-stack",
  "harbor-stack",
    "ci-runner-01",
    "dns-stack",
    "step-ca-stack",
    "authentik-stack",
    "proxy-stack",
    "monitoring-stack",
    "netbox-stack",
  "portainer-stack",
]


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


def topo_sort(nodes, deps_map, tie_key):
    incoming = {n: 0 for n in nodes}
    edges = {n: [] for n in nodes}
    for node in nodes:
        for dep in deps_map.get(node, []):
            if dep in incoming:
                incoming[node] += 1
                edges[dep].append(node)

    ready = sorted([n for n, count in incoming.items() if count == 0], key=tie_key)
    ordered = []

    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for child in edges[current]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
        ready.sort(key=tie_key)

    if len(ordered) != len(nodes):
        cycle_nodes = sorted([n for n, count in incoming.items() if count > 0])
        die("dependency cycle detected among selected stacks: " + ", ".join(cycle_nodes))

    return ordered


def validate_order(order, deps_map):
    index = {name: idx for idx, name in enumerate(order)}
    for name in order:
        for dep in deps_map.get(name, []):
            if dep in index and index[dep] > index[name]:
                die(f"invalid order: {name} depends on {dep}, but {dep} is scheduled later")


deps_map = {name: stack_meta[name]["depends_on"] for name in candidates}
platform = [name for name in candidates if stack_meta[name]["tier"] == "platform"]
apps = [name for name in candidates if stack_meta[name]["tier"] == "apps"]

if not requested and tier_filter in {"platform", "all"}:
    missing = [name for name in APPROVED_PLATFORM_ORDER if name not in platform]
    extra = sorted([name for name in platform if name not in APPROVED_PLATFORM_ORDER])
    if missing or extra:
        details = []
        if missing:
            details.append("missing=" + ", ".join(missing))
        if extra:
            details.append("extra=" + ", ".join(extra))
        die("platform metadata does not match approved bootstrap order: " + " ; ".join(details))

if requested:
    # For explicit runs, keep approved sequence for selected platform stacks.
    platform_order = [name for name in APPROVED_PLATFORM_ORDER if name in platform]
    for name in platform:
        if name not in APPROVED_PLATFORM_ORDER:
            die(f"selected platform stack {name} is missing from approved order list")
else:
    platform_order = [name for name in APPROVED_PLATFORM_ORDER if name in platform]

apps_order = topo_sort(apps, deps_map, lambda n: n)
ordered = platform_order + apps_order

# If explicit selection includes only unclassified stacks, preserve requested order.
if requested and not ordered:
    unclassified = [name for name in candidates if stack_meta[name]["tier"] not in {"platform", "apps"}]
    if not unclassified:
        die("no selected stacks mapped to supported deployment tiers")
    ordered = unclassified

validate_order(ordered, deps_map)

for name in ordered:
    print(name)
PY
}

tier_filter="all"
check_mode=false
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

mapfile -t ordered_stacks < <(resolve_stack_order "$tier_filter" "$explicit_csv")
(( ${#ordered_stacks[@]} > 0 )) || fail "no stacks resolved for execution"

export ANSIBLE_HOST_KEY_CHECKING="False"
export ANSIBLE_CONFIG="${ANSIBLE_DIR}/ansible.cfg"
export ANSIBLE_ROLES_PATH="${ANSIBLE_DIR}/roles"
export ANSIBLE_LOCAL_TEMP="/tmp/.ansible/tmp"
export ANSIBLE_SSH_CONTROL_PATH_DIR="/tmp/.ansible/cp"

for stack in "${ordered_stacks[@]}"; do
  inventory_file="${STACKS_DIR}/${stack}/inventory.yml"

  ensure_portainer_oauth_secret "$stack"
  ensure_portainer_edge_publish "$stack" "$check_mode"

  if [[ ! -f "$inventory_file" ]]; then
    log "SKIP ${stack}: inventory file not found (${inventory_file})"
    continue
  fi

  playbook_name="$(extract_ansible_playbook "$inventory_file")"
  if [[ -z "$playbook_name" ]]; then
    log "SKIP ${stack}: no ansible_playbook in inventory"
    continue
  fi

  if [[ "$playbook_name" == *.yml ]]; then
    playbook_file="${ANSIBLE_DIR}/playbooks/${playbook_name}"
  else
    playbook_file="${ANSIBLE_DIR}/playbooks/${playbook_name}.yml"
  fi

  if [[ ! -f "$playbook_file" ]]; then
    fail "${stack}: playbook file not found (${playbook_file})"
  fi

  cmd=(ansible-playbook -i "$inventory_file" "$playbook_file")

  # Always regenerate zone from EdgeManifests before deploying dns-stack so the
  # live zone is never stale with respect to declared routes.
  if [[ "$stack" == "dns-stack" ]]; then
    generated_zone="${REPO_ROOT}/terraform/lxc/.generated/coredns/coredns-lab.zone"
    generated_zone_dir="$(dirname "$generated_zone")"
    mkdir -p "$generated_zone_dir"
    log "Regenerating CoreDNS zone from EdgeManifests"
    python3 "${REPO_ROOT}/terraform/lxc/render-edge-coredns.py" \
      --stacks-dir "${REPO_ROOT}/terraform/lxc/stacks" \
      --seed-zone "${REPO_ROOT}/terraform/lxc/ansible/files/coredns-lab.zone" \
      --output-zone "$generated_zone"
    cmd+=(-e "coredns_generated_zone_src=${generated_zone}")
  fi

  if [[ "$check_mode" == "true" ]]; then
    cmd+=(--check)
  fi

  log "RUN ${stack}: ${cmd[*]}"
  "${cmd[@]}"
done

log "Completed provision orchestration"
