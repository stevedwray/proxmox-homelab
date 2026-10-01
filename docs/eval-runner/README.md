# eval-runner

Status: **done and in place (2026-10-01).** The harness runs on
`ai-services-stack` (pve-tiny), with a five-stage GPU-free self-test as its
deploy gate. Results publish to Nextcloud:
- the Tables table **Model evaluations** (21 historical rows, two
  comparable views, shared read-only with `steve`);
- `Reports/eval-runner/` (leaderboard.md/.csv, findings.md, per-run
  reports), shared with `steve`.

All 36 plan gates and 46 unit tests pass. No real scored run against
Framework has been made yet; that is an operator decision. Branch
`task/eval-runner` is not merged.

Runs the eval battery's lm_eval tests (GPQA, IFEval) from
`ai-services-stack` (`ai_seg`, on `pve-tiny`) as a client of whatever
model Framework's llama-server is serving. It replaces running them on
`framework` or garuda. The previous dedicated harness LXC (`ai-stack`,
VMID 116) was removed in the pve teardown.

See [`plan.md`](./plan.md) for decisions, steps and usage.

## Where things stand and what's next (checkpoint 2026-10-01)

**Live:**
- **eval-runner on `ai-services-stack`** (pve-tiny, 192.168.50.11):
  `eval-run gpqa|ifeval|resume|selftest|results|publish`.
- **Nextcloud:** Tables "Model evaluations" (table id 2, 21 historical
  rows, two Comparable views, shared read-only with steve) and
  `Reports/eval-runner/`, shared with steve.
- **Framework :8080:** still serving GLM-5.3-Flash (hand-started, not a
  systemd unit). Qwen `nathanw-llamacpp` and ComfyUI are stopped. One slot
  was busy at the checkpoint, likely the operator's CSE suite.

**Branches (not merged, the operator decides):**
- `task/eval-runner`: 16 commits.
- `task/glm-5.3-flash-eval`: 4 commits (GLM doc, including the CPU-spin
  §8).

**Pending operator decisions:**
1. **`leaderboard.csv` in Nextcloud** opens as plain text (no CSV
   viewer). Proposed: stop uploading it, keep it on the CT dry-run, and
   rely on the Tables table plus `leaderboard.md`. Alternatives: install
   Nextcloud Office (Collabora) or leave as is. **Awaiting the
   operator's answer.**
2. **Token budget:** add `--max-gen-toks` (for example 32k) as a
   separate, labelled non-comparable series for reasoning models? Default
   stays 8192.
3. **Rest of the battery:**
   - BFCL: the `bfcl` CLI, packageable.
   - RepoBench: the custom scripts are lost; lm_eval's
     `longbench_repobench-p` is a different benchmark.
   - AgentBench: 6.7 GB with Docker task servers.
4. **The first real scored run** against Framework. This needs explicit
   go-ahead (hours of GPU; check `/slots` and CSE first).
5. **Merging** `task/eval-runner` and `task/glm-5.3-flash-eval`.

**Known side issues (not fixed, out of scope):**
- `deploy-nextcloud-stack.yml`'s steve-user task sets `OC_PASS` without
  `docker exec -e`.
- GLM CPU spin on Framework (GLM doc §8): diagnose with
  `GGML_SCHED_DEBUG=2`, then try `--threads 4`, when Framework is idle.

**How to resume:**
- Read `plan.md`. Its prose has the operator sequences, and all 36 gates
  re-run green against the branch.
- The plan is regenerated from repo files by a generator script kept in
  the session scratchpad. If that's gone, edit `plan.md` by hand and
  re-run the gate check, which parses the YAML blocks and runs each
  `cmd`.

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
| eval-runner-06d–g (runmeta, selftest checks, unit tests) | done 2026-10-01, all critical gates pass |
| Operator: deploy to pve-tiny | done 2026-10-01. Latest deploy (`dca91fc4`): `failed=0`, all 4 self-test stages OK |
| eval-runner-06h–j, 08–10 (publish, Nextcloud, findings, manifest) | done 2026-10-01, all critical gates pass |
| Operator: Nextcloud deploy + app password + publish | done 2026-10-01 |
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

### 2026-10-01: request guard, run metadata, resume, response flags, unit tests

Operator direction: do everything possible before any run exercises the
local models. Commits `5181323c` and `dca91fc4`.

**Verified first, from lm_eval 0.4.12's installed source:**
- The chat payload sends `max_tokens`, `temperature` (task default 0;
  both tasks pin 0.0), `stop` and `seed: 1234`.
- `--use_cache` commits each response as it arrives (`add_partial` into
  `SqliteDict(autocommit=True)`).
- The cache key ignores the model.
- llama-server's `/props` doesn't expose `--chat-template-kwargs`.

**Built:**
- **`runmeta.py` (start/exec/check):** server fingerprint, run naming,
  and the exact lm_eval argv, all in `run.json`.
- **`eval-run resume`:** refuses if the fingerprint changed; `--force`
  overrides.
- **`--note`.**
- **`selftest_checks.py`:** asserts what lm_eval actually sent.
- **Response-quality flags** in `summarize.py`.
- **`mock_openai.py` additions:** request log, every-Nth-empty replies,
  `/props`, configurable port and model path.
- **Selftest output pruning:** keeps the 5 most recent.
- **22 unit tests:** `python3 -m unittest discover -s
  terraform/lxc/ansible/files/eval-runner -p "test_*.py"`.

**Evidence:**
- **Selftest on the CT:**
  1. `Cached requests: 0, Requests remaining: 4`, then `checks OK (4
     requests)` (max_tokens 8192, temperature 0, seed 1234, model id), and
     empty-flag total 2 as configured.
  2. On resume: `Cached requests: 4, Requests remaining: 0`, and the mock
     saw no new requests.
  3. Change detection: `props.model_path: '/models/selftest-mock.gguf' ->
     '/models/some-other-model.gguf'`, exit 3.
- **Host paths on the CT:**
  - Bad arguments, path traversal and unknown runs all exit 2 before
    starting anything.
  - A planted run whose recorded server differs from Framework was
    refused by `eval-run resume`, with a field-by-field diff. That needed
    only GETs of `/v1/models` and `/props`, with no inference and no
    container started. It also confirmed that `runmeta` parses the real
    llama-server `/props`.
- **Flags on real history:** Qwen3.6-35B's GPQA redo has 49 of 198 empty
  responses and 54 unparsed; its IFEval redo has 16 of 541 empty. These
  match hand counts. Recorded in the eval-battery doc as a caveat on its
  leading 57.07% GPQA score.
- **Deploys:** `ok=105 failed=0` both times, self-test OK. Five selftest
  dirs are kept, about 140 KB each.

`plan.md` was regenerated from the deployed files (13 steps, 26 gates).
Embedded content was compared byte for byte with the repo, and all gates
pass.

### 2026-10-01: historical comparison, backup coverage, battery survey

Commit `9e780305` (deployed: `ok=105 failed=0`, self-test OK).

**Comparability rule (`summarize.exclusion_reason`):** a historical result
counts only if lm_eval's own recorded config shows a full run
(`limit: null`) with `max_gen_toks` 8192.
- Surveyed all 22 historical GPQA/IFEval results on framework. The rule
  selects exactly the eval-battery doc's valid set, with matching numbers:
  Gemma4-26B 43.94/92.98, A4B-QAT 27.27/89.83, Laguna 24.24/75.42,
  Qwen3.6-35B redo 57.07/90.39, Qwen3.8-27B 43.43/89.46, Qwen3-Coder-30B
  IFEval redo 81.33.
- It excludes the Gemma4 pilots, the Bug 6 Qwen3.6 runs (GPQA 0.00,
  IFEval 17.74), and Qwen3-Coder-30B's uncapped `ctx163k` GPQA 11.62.

**Import:** 36 files, ~42 MB, into `/srv/eval-runner/results/_historical/`
(uid 1000). Exact commands are in `plan.md` ("import historical
results"). `eval-run results` now prints a historical section plus an
excluded list with reasons.

**Finding: GPQA empty answers under the 8192 budget.**

| Model | Empty GPQA answers (of 198) |
|---|---|
| Gemma4-26B | 91 |
| Gemma4-26B-A4B-QAT | 134 |
| Laguna S2.1 | 114 |
| Qwen3.8-27B | 105 |
| Qwen3.6-35B | 49 |

Historical GPQA therefore largely measures finishing inside 8192 tokens.

I tried a derived "accuracy on parsed answers" figure and removed it
again. It was biased: answered subsets skew easy and differ per model (it
gave Qwen3.8-27B an implausible 94.5%).

**Backups, checked read-only on pve-tiny:**
- Job `48087a29…`: 12:30, `all 1`, `exclude 910`, `pbs-iscsi`, enabled.
- CT 50013 snapshots: 2026-09-29T23:32Z and 2026-09-30T23:34Z.
- `rootfs` has no `backup=0`, and `mp0` (Docker) is `backup=1`.

Results are covered, with PBS keep-last-2 retention.

**Battery survey:**
- The custom RepoBench scripts are lost; they were on the ai-stack LXC
  only.
- BFCL was run with the `bfcl` CLI on framework; only logs and results
  remain.
- AgentBench is a 6.7 GB `Eugleo/agent-bench` checkout on garuda.

None of these is packaged yet; that needs operator decisions.

### 2026-10-01: results and findings in Nextcloud (Tables + reports)

Operator direction: tabulate and document results nicely for comparison
and analysis, in Nextcloud. Use existing data where possible and
synthetic data where required.

**Research:**
- Nextcloud 35.0.0 had no table or spreadsheet app.
- Tables 2.3.1 (stable) supports it.
- Collabora/ONLYOFFICE were skipped: they're heavy and not needed for
  sortable, filterable tables.

**Built:** commits `842895fe`, `3efbf3ce` and `d77bc30c`.
- `publish.py` with `--dry-run`, and `eval-run publish`.
- `mock_nextcloud.py`, which enforces the Tables input contract.
- Selftest stage 5: publish twice over real HTTP, no duplicates.
- `docs/eval-runner/findings.md`.
- Nextcloud playbook tasks: install Tables, create the `eval-reports`
  account.
- ai-services playbook: Nextcloud env, `findings.md` into the image, the
  folder-share play.
- Manifest field `services/nextcloud:NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD`.
- 46 unit tests.

**Live sequence:**
1. **Slip:** a probe `occ app:enable tables` installed Tables 2.3.1 on
   prod outside the playbook (`app:enable` installs missing apps). It was
   the intended end state. The playbook run then reported `ok`
   (idempotent).
2. **`nextcloud-stack` deploy on `pve`:** `ok=102 failed=0`, and
   `eval-reports` was created (the app container wasn't restarted).
   Side note: the existing `steve` user task sets `OC_PASS` without
   `docker exec -e`, so it would only work if the user already exists.
   Left as is.
3. **App password:** the operator piped it straight into OpenBao
   (`WRITE OK: services/nextcloud now at version 6`). Verified it loads
   (72 alnum characters) and authenticates: WebDAV 207, Tables API 200.
4. **ai-services deploy:** `failed=0`, self-test OK including stage 5,
   folder share created.
5. **First real publish: failed at `PUT /views/2` with HTTP 500.** The
   Nextcloud log showed `foreach() argument must be of type array|object,
   string given` in `ViewUpdateInput.php`. Read the Tables PHP source and
   fixed it (`d77bc30c`):
   - `columnSettings`, filter and sort are now sent as real arrays;
   - views are re-applied on every publish, which repaired the
     half-created one;
   - the table column order and sort are set through OCS v2;
   - network errors are reported cleanly;
   - the mock now enforces the contract.
6. **Later publishes:**
   `published 21 files … 0 rows created, 0 updated, 21 unchanged`, both
   times. The 21 rows were created by the failed attempt, and the
   round-trip comparison is now proven.
7. **Verified through the API:**
   - table 2 "Model evaluations": 21 rows, 20 columns, Key first, sorted
     Task ASC then Score DESC;
   - views "Comparable: GPQA/IFEval" with is-equal filters and Score DESC
     sort;
   - table share to `steve`, read-only;
   - folder `Reports/eval-runner` shared to `steve` (perms 1), with
     leaderboard.md/.csv, findings.md and historical/.
8. **Cleanup:** deleted the auto-created "Welcome to Nextcloud Tables!"
   table owned by `eval-reports`.

**Data used:** the published rows are the real historical results from
framework. Synthetic data was only used where there was no real data
yet: the selftest's mock-LLM run and the mock-Nextcloud publish, plus
unit-test fixtures. No synthetic rows were published to the real
Nextcloud.

`plan.md` was regenerated (19 steps, 36 gates, all pass). Step 01's
manifest gate is now scoped to its own entry, because the manifest
legitimately has two additions.
