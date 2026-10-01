# eval-runner

Status: **done and in place on pve-tiny (2026-10-01).** Every plan step is
applied, and all 19 plan gates pass against the branch. The deploy runs a
GPU-free self-test (`eval-run selftest`), which passes. No real scored run
against Framework has been made yet; that is a separate operator decision,
because it occupies the GPU for hours. Branch `task/eval-runner` is not
yet merged to `stable`.


Runs the eval battery's lm_eval tests (GPQA, IFEval) from
`ai-services-stack` (`ai_seg`, on `pve-tiny`) as a client of whatever
model Framework's llama-server is serving. It replaces running them on
`framework` or garuda. The previous dedicated harness LXC (`ai-stack`,
VMID 116) was removed in the pve teardown.

See [`plan.md`](./plan.md) for decisions, steps and usage.

## Progress

| Step | Status |
|---|---|
| eval-runner-01-manifest-hf-token | done 2026-10-01, all critical gates pass |
| Operator: write HF_TOKEN | done 2026-10-01 (loads via `printenv`; token fetches `gpqa_diamond.csv` with HTTP 206, anonymous gets 401) |
| eval-runner-02-dockerfile | done 2026-10-01, all critical gates pass |
| eval-runner-03-eval-run-script | done 2026-10-01, all critical gates pass |
| eval-runner-04-playbook-play | done 2026-10-01, all critical gates pass |
| eval-runner-05-battery-doc-pointer | done 2026-10-01, all critical gates pass |
| eval-runner-06a/b/c (selftest server, script, summariser) | done 2026-10-01, all critical gates pass |
| eval-runner-07-stack-yaml-pointer | done 2026-10-01, all critical gates pass |
| Operator: deploy to pve-tiny | done 2026-10-01. Third deploy (`2793ec09`) is current: `failed=0`, self-test OK |
| Smoke test | replaced by the deploy-time `eval-run selftest` (passes). A real pilot against Framework is optional, operator's call |

## Hand-backs

### 2026-10-01: steps 01–05 (run directly by Claude Code, not the local model)

Each file was written from the same tested scratch copies the plan's literal
content was generated from. Gate results:

- **01:** `only-hf-token-added` → `OK`; `one-line-diff` → `1  1  secrets/manifest.json`.
- **02:** `exact-content` → `542fdf7e…c4fb` (match).
- **03:** `exact-content` → `dfc3a470…c36f` (match); `executable` → `OK`;
  `shellcheck` → clean.
- **04:** `exact-appended-play` → `2b32c4ce…99b8` (match); `append-only` →
  `66  0`; `syntax-check` → exit 0.
- **05:** `section-present` → `1`; `append-only` → `0`.

From this commit until the `HF_TOKEN` value is written, `./with-secrets*`
loads on this branch fail closed. Nothing should deploy from the branch
before that.

### 2026-10-01: deploy to pve-tiny

Ran `TASK_APPROVAL=eval-runner-deploy ./with-secrets-prod-tiny
scripts/provision.sh --stack ai-services-stack` (inventory target
`192.168.50.11` checked first).

- **First attempt, rc=1:** the image build failed after `pip install`
  had succeeded. `python -c "import nltk; ..."` raised `ImportError:
  Blocked import of locale from current working directory`. nltk 3.10.1
  refuses imports that resolve under the cwd, and the build's default cwd
  is `/`, which contains the stdlib. Reproduced on framework (same nltk):
  `-P` doesn't help, running from any other directory does.
- **Fix (`156fc493`):** move `WORKDIR /results` above the `RUN`. The
  plan's literal Dockerfile and step 02's hash were updated to match
  (`11e7dce6…7e85`).
- **Second attempt, rc=0:** recap `ok=101 changed=9 failed=0 ignored=1`.
  The one ignored failure is the existing `Timeout when waiting for
  192.168.20.11:443` check in the Docker-base play, unrelated. The
  eval-runner play's reachability task printed `Framework /v1/models
  returned HTTP 200`. Image `eval-runner:local` is 780 MB. `curl` and
  `python3` are both present on the CT, which settles the open question in
  `plan.md`.

### 2026-10-01: smoke test (partial, stopped)

`eval-run ifeval --pilot` started `eval-glm-5.3-flash-ifeval-pilot-20261001T020318Z`.

**Proven:**
- Model id auto-detected as `glm-5.3-flash`.
- lm_eval picked up `timeout: 3600`, `num_concurrent: 1` and
  `max_gen_toks: 8192`.
- Framework's `/slots` showed the request being generated, from
  `192.168.50.11`.

**Not proven:**
- A completed run and results files.
- GPQA (the gated dataset, inside the container).

The container was stopped (`docker stop`, exit 137) and removed after
about 10 minutes, with 0 of 40 prompts finished, at operator request.
The operator hadn't intended this work to start GPU jobs, and a
CyberSecEval suite from `cse_seg` (`192.168.100.70`) was running against
the same server at the time.

**Timing note for the next attempt:** with reasoning at `high`, a single
IFEval answer from GLM-5.3-Flash ran to 6,387 tokens. Sharing the server
with another client roughly halves per-request speed (10 vs ~18 tok/s).
Budget a couple of hours for a 40-prompt pilot, and run it when nothing
else is using Framework.

### 2026-10-01: GPU-free self-test, results summary, non-root image

Operator direction: build the harness out thoroughly and put it in place,
without running GPU jobs. Added in `2793ec09`:

- **`eval-run selftest`:** runs `mock_openai.py` (a stdlib stand-in
  OpenAI server, `127.0.0.1:18080`) inside the image, then both tasks at
  `--limit 2` with the real run's lm_eval flags. `summarize.py --check`
  is the pass/fail. The deploy runs it as a gate.
- **`eval-run results`:** headline GPQA (flex/strict) and IFEval
  (prompt strict/loose) per run. Checked locally against framework's
  historical Qwen3.6-35B `results_*.json`, where it reproduces 57.07% and
  90.39%/91.87%. `--check` correctly fails a GPQA-only directory.
- **Non-root image (uid 1000):** the results directory is chowned to 1000
  (that uid is the CT's existing `automation` account), and the HF cache
  moved to the `eval-runner-hf` volume. The old root-owned
  `eval-runner-hf-cache` volume is removed by the play.
- **Sorted pip pins**, plus a comment on why `--only-binary` isn't
  possible (Sonar S7018/S8541). The "2 high vulnerabilities" Sonar flag
  is in the `python:3.12-slim` base image, which deep-research uses too.
  Not addressed here.
- **A pointer in `ai-services-stack/stack.yaml`'s header comment.**

Deploy: `ok=105 changed=11 failed=0 ignored=1` (the usual
`192.168.20.11:443` check). The self-test summary was `GPQA flex 0.00%,
GPQA strict 0.00%, n=2, IFEval p-strict 50.00%, IFEval p-loose 50.00%,
n=2` / `selftest OK`. These scores are meaningless (canned replies). What
counts is that the gated GPQA dataset downloaded as the non-root user and
both tasks scored.

Manual checks on the CT afterwards:
- `eval-run --help` works, and `eval-run results` prints `no runs yet`.
- A second self-test takes 15 s with cached datasets.
- The `samples_ifeval_*.jsonl` response is the mock's reply, so the
  request path works end to end.
- No leftover `eval-*` containers.

`plan.md` was regenerated so its literal content and hashes match the
deployed files. All 19 gates were re-run against the branch and pass.
