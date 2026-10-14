#!/usr/bin/env bash
# Run on Framework (ssh ... 'bash -s' < this file). docs/ctx-bug-test/plan.md, ctx-08.
# Writes llama-swap's config only if the dry run lists all 16 ctx-test entries
# plus any extra entry ids given as arguments (ssh ... 'bash -s -- <id> ...');
# otherwise prints what is missing and exits 1 without writing anything.
# --cleanup inverts the ctx-entry gate for ctx-14 and removes Laguna fork.
set -euo pipefail
cleanup=false
if [[ "${1:-}" == --cleanup ]]; then
  cleanup=true
  shift
  if (( $# )); then
    echo 'GATE FAILED: --cleanup takes no extra entry ids -- nothing written'
    exit 1
  fi
fi
out="$(llama-builds swap-config --dry-run)"
printf '%s\n' "$out"
unchanged=false
if [[ "$out" =~ ^llama-swap\ config\ unchanged\ \(([0-9]+)\ entries\)$ ]]; then
  unchanged=true
  count="${BASH_REMATCH[1]}"
  # Use the installed generator's read-only functions, including overrides
  # and current/candidate links. Verify exact bytes before trusting its IDs.
  # No CLI main, HTTP, Redis, config write or model load is invoked here.
  if ! out="$(python3 - "$(command -v llama-builds)" "$count" <<'PY'
import runpy
import sys
from pathlib import Path

tool = runpy.run_path(sys.argv[1])
cfg = tool['load_config']()
entries = tool['swap_entries'](cfg, tool['load_catalog'](cfg))
expected = tool['render_swap'](cfg, entries)
if len(entries) != int(sys.argv[2]):
    raise SystemExit('unchanged entry count changed during validation')
if Path(tool['swap_cfg'](cfg)['config']).read_bytes() != expected.encode('utf-8'):
    raise SystemExit('existing config differs from generated config during validation')
print('Verified unchanged config entries:')
for entry, _ in entries:
    print('  ' + entry)
PY
)"; then
    echo 'GATE FAILED: unchanged config could not be verified -- nothing written'
    exit 1
  fi
  printf '%s\n' "$out"
fi
if [[ "$cleanup" == true ]]; then
  # Invert the catalogue-test gate for ctx-14. A successful but unfamiliar
  # preview must not turn into a write just because it contains no ctx IDs.
  if ! grep -qE '^(would write [0-9]+ entries:|Verified unchanged config entries:)$' <<<"$out"; then
    echo 'GATE FAILED: unrecognized cleanup preview -- nothing written'
    exit 1
  fi
  if grep -qE '^  [^[:space:]]+-ctx[^[:space:]]*$' <<<"$out"; then
    echo 'GATE FAILED: context-test entries remain -- nothing written'
    exit 1
  fi
  for id in qwen3.8-flash-next-q4-nathanw qwen3.8-flash-next-q4-upstream qwen3.8-flash-next-q4-hip laguna-s-2.1-upstream laguna-s-2.1-hip; do
    if ! grep -qxF "  $id" <<<"$out"; then
      echo "GATE FAILED: cleanup is missing $id -- nothing written"
      exit 1
    fi
  done
  if grep -qxE '  laguna-s-2[.]1-nathanw(-candidate)?' <<<"$out"; then
    echo 'GATE FAILED: broken Laguna fork backend remains -- nothing written'
    exit 1
  fi
  if [[ "$unchanged" == true ]]; then
    echo 'GATE OK: no ctx-test entries or Laguna fork; verified unchanged -- no write or reload'
    exit 0
  fi
  echo 'GATE OK: no ctx-test entries or Laguna fork; ordinary tested entries retained; writing'
  llama-builds swap-config
  exit 0
fi
missing=""
for m in qwen3.8-flash-next-q4 laguna-s-2.1; do
  for b in nathanw upstream; do
    for n in 32k 64k 96k 131k; do
      id="$m-$b-ctx$n"
      grep -qxF "  $id" <<<"$out" || missing="$missing $id"
    done
  done
done
for id in "$@"; do
  grep -qxF "  $id" <<<"$out" || missing="$missing $id"
done
if [ -n "$missing" ]; then
  echo "GATE FAILED: dry run is missing:$missing -- nothing written"
  exit 1
fi
if [[ "$unchanged" == true ]]; then
  echo "GATE OK: all 16 ctx-test entries and $# extra present; verified unchanged -- no write or reload"
  exit 0
fi
echo "GATE OK: all 16 ctx-test entries and $# extra present; writing"
llama-builds swap-config
