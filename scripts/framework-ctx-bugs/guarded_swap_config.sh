#!/usr/bin/env bash
# Run on Framework (ssh ... 'bash -s' < this file). docs/ctx-bug-test/plan.md, ctx-08.
# Writes llama-swap's config only if the dry run lists all 16 ctx-test entries
# plus any extra entry ids given as arguments (ssh ... 'bash -s -- <id> ...');
# otherwise prints what is missing and exits 1 without writing anything.
set -euo pipefail
out="$(llama-builds swap-config --dry-run)"
printf '%s\n' "$out"
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
echo "GATE OK: all 16 ctx-test entries and $# extra present; writing"
llama-builds swap-config
