# PentAGI test-harness runner

Runs a sequence of PentAGI flows against `harness-target` (192.168.1.55),
varying the custom llama.cpp stack's config between runs — gpt-oss-120b vs
Laguna S 2.1 as the `adviser` role, plus Qwen3.6's own ctx-size/
reasoning-budget. See `docs/pentagi-stack/test-harness-design.md` and
`docs/pentagi-stack/harness-target.md` for the background.

Designed to run **on the `pentagi-stack` LXC (192.168.70.10)**,
independent of any interactive session — start it once and it works
through the whole sequence unattended.

## Prerequisites

- This host has a dedicated SSH key (`/root/.ssh/id_ed25519`) authorized
  on `framework.gibbsgreatly.xyz` for the `steve` user, added 2026-07-30
  specifically for this runner. **Temporary — remove both this key from
  framework's `authorized_keys` and the matching `pentest_seg -> 192.168.1.8:22`
  MikroTik firewall rule once testing is done.**
- `PENTAGI_ADMIN_PASSWORD` must be set in the environment before running
  (not stored in `test_sequence.json`).

## Running

```bash
export PENTAGI_ADMIN_PASSWORD='...'

# Preview the planned runs without making any changes:
python3 run_sequence.py --dry-run

# Run a single config first (recommended before trusting the full sequence):
python3 run_sequence.py --only 1

# Run the full 6-run sequence, detached so it survives disconnect:
nohup python3 run_sequence.py > run.log 2>&1 &
disown
```

## Checking progress

```bash
tail -f run.log
ls docs/pentagi-stack/artifacts/harness-runs/   # one result file per completed run
```

## Stopping mid-sequence

`Ctrl-C` if running in the foreground; `kill <pid>` if backgrounded (find
the pid via `ps aux | grep run_sequence`). The currently-running PentAGI
flow itself is not automatically stopped — use the UI or `stopFlow` via
GraphQL if you want to abort it too.

## What each run does

1. If the adviser model is changing from the previous run: unload the old
   one on the router, edit `custom.provider.yml`'s `adviser` section, and
   recreate the `pentagi` container.
2. If this run uses Laguna: stop any Ollama-resident models on framework
   first (Ollama holding models indefinitely was the actual cause of an
   OOM hit while setting this up — Laguna's ~68GiB footprint leaves very
   little headroom otherwise) and check available memory before
   proceeding; skips the run (logs it, doesn't crash the sequence) if
   there isn't enough.
3. Rewrites the Qwen3.6 and adviser sections of `models-preset.ini` and
   hits the router's hot-reload endpoint.
4. Logs into PentAGI, creates a flow against `harness-target` with the
   fixed prompt, and polls until it finishes, fails, or hits the
   3-hour watchdog timeout (in which case it calls `stopFlow` rather
   than block indefinitely).
5. Writes a result file to `docs/pentagi-stack/artifacts/harness-runs/`
   with the config used, final task/subtask status, and toolcall counts
   per subtask — a starting point for judging each run, not a substitute
   for actually reading the flow's content afterward.
