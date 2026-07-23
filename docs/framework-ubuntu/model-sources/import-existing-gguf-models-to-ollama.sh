#!/usr/bin/env bash
# One-time catch-up: imports every GGUF already downloaded for LM
# Studio/llama.cpp (/storage/models/llm) into Ollama's own catalog, so all
# three backends serve the same model library without re-downloading
# anything. Not an Ansible task deliberately -- model-catalog population is
# an operator action in this repo, not declarative state (same precedent as
# LM Studio's own catalog note in docs/framework-ubuntu/decisions.md
# Decision 6).
#
# Requires: framework-desktop-ollama.yml already applied with the
# /mnt/llm-models read-only bind mount (added alongside this script).
#
# Naming convention: <lowercased-filename-minus-quant-suffix>:<quant-suffix>
# e.g. Llama-3.3-70B-Instruct-Q4_K_M.gguf -> llama-3.3-70b-instruct:q4_k_m
# -- matches the existing eval-*:q4_k_m/q6_k models already in this Ollama
# instance. Files whose byte size already matches an existing Ollama model
# are skipped (they're already imported, just under a different name).
#
# Run directly on framework.gibbsgreatly.xyz:
#   bash import-existing-gguf-models-to-ollama.sh [--dry-run]
set -euo pipefail

MODELS_DIR="/storage/models/llm"
CONTAINER="ollama"
API="http://127.0.0.1:11434"
SIZE_TOLERANCE_BYTES=10485760 # 10MiB
DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

existing_sizes="$(curl -fsS "${API}/api/tags" \
  | python3 -c 'import json,sys; print("\n".join(str(m["size"]) for m in json.load(sys.stdin)["models"]))')"

already_present() {
  local file_size="$1" s diff
  while IFS= read -r s; do
    [ -z "${s}" ] && continue
    diff=$(( file_size > s ? file_size - s : s - file_size ))
    if [ "${diff}" -lt "${SIZE_TOLERANCE_BYTES}" ]; then
      return 0
    fi
  done <<<"${existing_sizes}"
  return 1
}

derive_name_tag() {
  local lower="$1"
  if [[ "${lower}" =~ ^(.*)-(q[0-9][a-z0-9_]*)(-imat)?$ ]]; then
    echo "${BASH_REMATCH[1]}:${BASH_REMATCH[2]}${BASH_REMATCH[3]}"
  else
    echo "${lower}:latest"
  fi
}

for f in "${MODELS_DIR}"/*.gguf; do
  [ -e "${f}" ] || continue
  base="$(basename "${f}" .gguf)"
  lower="$(echo "${base}" | tr '[:upper:]' '[:lower:]')"
  size="$(stat -c%s "${f}")"

  if already_present "${size}"; then
    echo "skip (already present, size match): ${base}"
    continue
  fi

  name_tag="$(derive_name_tag "${lower}")"
  container_path="/mnt/llm-models/$(basename "${f}")"

  if "${DRY_RUN}"; then
    echo "[dry-run] would import: ${base} -> ${name_tag} (FROM ${container_path})"
    continue
  fi

  echo "importing: ${base} -> ${name_tag}"
  docker exec "${CONTAINER}" sh -c "printf 'FROM %s\n' '${container_path}' > /tmp/import.Modelfile"
  docker exec "${CONTAINER}" ollama create "${name_tag}" -f /tmp/import.Modelfile
done

echo
echo "Current Ollama catalog:"
docker exec "${CONTAINER}" ollama list
