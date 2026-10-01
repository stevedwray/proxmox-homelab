# eval-runner: the eval battery from ai-services-stack

Status: **all steps done.** GPQA/IFEval and Nextcloud publishing are
deployed to pve-tiny (2026-10-01). BFCL, AgentBench and RepoBench
(rebuilt) are built and unit-tested; their deploy and selftest are in
`README.md`. The literal content and hashes below match the files on the
branch.

## Goal

Run the eval battery (`docs/framework/eval-battery-phase2-plan.md`),
except CyberSecEval (it has its own panel): GPQA (diamond, CoT
zero-shot), IFEval, BFCL, AgentBench and RepoBench. They run from
`ai-services-stack` against whatever model Framework's llama-server is
serving on `:8080`, instead of on `framework` itself or garuda. The whole
harness has to be verifiable without using Framework's GPU.

## Decisions (resolved with the operator, 2026-10-01)

- **Host: `ai-services-stack`, not a new LXC.** A GPQA run occupies
  Framework anyway, so nobody is using the local-AI services at the same
  time and isolation buys nothing. The CT is already in `ai_seg`.
- **No model switching.** The runner is a client of whatever llama-server
  serves. The model id comes from `/v1/models`.
- **CyberSecEval is out of scope.** It has its own panel
  (`docs/cyberseceval-panel/`).
- **A one-shot Docker image plus a script, not a compose service.** A
  `provision.sh --stack ai-services-stack` redeploy therefore never kills
  a long run.
- **Comparable with historical results.** lm_eval is pinned to 0.4.12,
  with the dependency versions of the `framework` venv behind every number
  in the eval-battery doc. Runs pass `--apply_chat_template --log_samples
  --gen_kwargs max_gen_toks=8192` (Bug 6), and the pilot size is
  `--limit 40`. Both task configs pin `temperature: 0.0`, so every request
  is greedy: same as all historical results, and different from GLM's
  recommended 1.0. Kept for comparability, deliberately.
- **Request timeout 3600 s** (lm_eval's default of 300 s is shorter than
  one 8192-token answer at about 18 tok/s).
- **`runmeta.py` owns what a run is.** It takes the server fingerprint
  from `/v1/models` and `/props` (model path, build, n_ctx, sampling
  defaults, chat-template hash), chooses the run name, and builds the
  exact lm_eval argv, all stored in `<run>/run.json`. Start, resume and
  selftest all go through it.
- **Resume, per run.** Each run has its own lm_eval `--use_cache` database,
  which commits each response as it arrives. `eval-run resume <run>`
  replays answered requests and refuses if the server fingerprint has
  changed (`--force` overrides). There is no cache shared across runs:
  lm_eval's cache key ignores the model, and server-side chat-template
  kwargs (such as GLM's `reasoning_effort`) aren't visible over the API.
  Those go in `--note`.
- **Verifiable without the GPU.** `eval-run selftest` runs the real
  start/exec/check path against `mock_openai.py` inside the image. The
  deploy runs it as a gate. Real runs against Framework are a separate,
  explicit operator decision.
- **Response-quality flags.** `eval-run results` counts empty responses
  per question (and unparsed GPQA answers), following the eval battery's
  "inspect raw output" rule.
- **Non-root image (uid 1000).** The host script never reads secrets
  itself; containers get them only via `--env-file`.
- **Results go to Nextcloud (operator request, 2026-10-01).** This uses
  Nextcloud Tables, not an office suite. There is one table, "Model
  evaluations": one row per (run, task), upserted by a Key column. It has
  saved views "Comparable: GPQA", "Comparable: IFEval" and the two
  "32k budget" views, and is shared read-only with `steve`.
  - Files: per-run `report.md` and `manifest.json` (the reporting
    `CONVENTION.md`), plus `leaderboard.xlsx`, `leaderboard.md` and
    `findings.md`, under `Reports/eval-runner/`. The folder is shared to
    `steve` by the existing `nextcloud_folder_share` role.
  - `leaderboard.xlsx` replaced `leaderboard.csv` (operator, 2026-10-01:
    the CSV opened as plain text, and wide markdown tables read badly).
    It has one ranked sheet per task and token-budget series, an "All
    results" sheet with filters, and a "Notes" sheet. It opens as a
    spreadsheet in Nextcloud Office. `publish` deletes the old CSV.
- **Token-budget series (operator, 2026-10-01).** `--max-gen-toks N`
  (N above 8192, e.g. 32768) starts a separate series: the run name gets
  `-32k`, the row gets Series `32k` and Comparable `no`, and it is ranked
  only against runs at the same budget. Budgets below 8192 are refused
  (that's Bug 6). `start` also refuses a budget the server's per-slot
  context can't hold, and the request timeout grows with the budget.
  - Publisher: the service account `eval-reports`. Only its app password
    is secret (`services/nextcloud:NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD`).
  - `samples_*.jsonl` never leave the CT (GPQA licence).
  - `findings.md` is written by hand, in the repo.
- **The rest of the battery (operator, 2026-10-01).** Each benchmark
  gets a wrapper (`<harness>_run.py`) that runs it against the run's
  server and writes an lm_eval-shaped `results_*.json` with
  `config.eval_runner` (harness, version, series, exclusion, runtime), so
  `results`, `publish`, the table and the xlsx treat every benchmark
  alike. BFCL and AgentBench get their own images (their pins conflict
  with lm_eval's); RepoBench runs in the main image.
  - **BFCL: same as history.** bfcl-eval 2025.8.6.2, v3 `simple` (400
    cases), default temperature 0.001, native function calling, no
    `max_tokens`. Installed under the exact package set of framework's
    BFCL venv (`bfcl-constraints.txt`). One generic handler is
    registered at start-up instead of the per-model handlers edited into
    framework's site-packages.
  - **AgentBench: os-std, 100 episodes, seed 42, on ai-services-stack's
    Docker.** Pinned commit `0cfef97` (checksum-verified tarball), the
    historical sample patch, temperature 0, `max_tokens` 3072. The run
    container gets the CT's Docker socket; each episode's sandbox runs
    with networking disabled. The sandbox image pre-installs every
    package the task inits fetch, so the tasks see what they saw with
    network. `agentbench.patch` also reads the API key from the
    environment (no secret in any config file) and raises the HTTP
    timeout from 120 s to 3600 s (slow models timed out mid-answer).
  - **RepoBench: rebuilt as a new series.** The historical scripts are
    lost. The rebuild follows upstream RepoBench (prompt construction,
    first-non-comment-line extraction, EM/ES, sample-weighted average)
    on the same v1.1 Python data, with raw completions and greedy
    decoding, 100 seeded samples per setting and level. It is not ranked
    against the six historical RepoBench numbers.
  - **History imported where data survives:** 18 BFCL scores from
    framework and 2 AgentBench outputs from garuda
    (`import_history.py`).
- **`HF_TOKEN` goes in `shared/external-apis`.** GPQA is gated (anonymous
  fetch: HTTP 401). Framework's key is the existing
  `LLM_GPU_STACK_API_KEY`.

## Facts checked (2026-10-01)

- **BFCL (bfcl-eval 2025.8.6.2, read from the wheel):**
  `MODEL_CONFIG_MAPPING` is one dict shared by every module, and
  generation runs in threads, so registering a model at start-up works.
  `bfcl evaluate` asserts that every case has an answer, so the wrapper
  calls the same `ast_file_runner` itself on the generated cases. A
  re-run skips answered cases, but also skips "Error during inference"
  entries, so the wrapper drops those first. All 106 pinned packages
  resolve to Python 3.12 wheels.
- **AgentBench (garuda checkout):** os-std is the prompt-injection
  variant (800 episodes = 14 tasks x ~70 variants). Init scripts
  `apt-get install` netcat or libssl-dev (100 episodes),
  `--reinstall wamerican` (140) and net-tools/iproute2/lsof, and their
  exit codes are ignored. The historical sandboxes were built
  `FROM ubuntu` = 26.04. Only `FastChatAgent` imports the torch stack.
  The assigner resumes from an existing output folder. The 43 pinned
  packages resolve to Python 3.11 wheels.
- **RepoBench upstream (Leolty/repobench @ e0cfd34):** `run.py`
  completes raw prompts (no chat), 128 new tokens, at levels 2k-16k, with
  prompts cut to 15800 tokens. `eval.py` weights per-setting EM/ES by
  sample count. The dataset (`tianyang/repobench_python_v1.1`, 473 MB,
  not gated) is the same set of parquet files as framework's
  `repobench-convert` copy.

- **Network:** `ai_seg → framework:8080` and `ai_seg → internet:443` are
  already allowed. No firewall change is needed.
- **`OPENAI_API_KEY` name clash:** `shared/external-apis` holds a real
  `OPENAI_API_KEY`. The runner only ever sees
  `/etc/eval-runner/eval-runner.env` (0600), which carries Framework's key
  under that name.
- **lm_eval 0.4.12 internals (read from the installed source):**
  - `LocalChatCompletion._create_payload` sends `max_tokens`
    (= `max_gen_toks`), `temperature` (task value, default 0), `stop` and
    `seed: 1234`.
  - The API model calls `cache_hook.add_partial` per response into a
    `SqliteDict(autocommit=True)`, which is why resume works mid-run.
  - The selftest confirms both empirically.
- **nltk 3.10.1** refuses imports that resolve under the cwd, and the
  build's default cwd `/` contains the stdlib. Hence `WORKDIR /results`
  before the first `RUN`.
- **Dependencies:** the pins resolve for Python 3.12 (72 packages, no
  torch). Four dependencies are sdist-only, so `--only-binary` isn't
  possible.
- **`summarize.py` against real history:** it reproduces Qwen3.6-35B's
  documented numbers (GPQA 57.07%, IFEval 90.39%/91.87%) and flags 49 of
  198 empty GPQA answers and 16 of 541 empty IFEval answers. Both counts
  were cross-checked by hand.
- **Historical comparability rule:** lm_eval records `config.limit` and
  `config.gen_kwargs` in every results file. "Full run with
  max_gen_toks=8192" selects exactly the runs the eval-battery doc treats
  as valid and excludes pilots, the Bug 6 runs, and Qwen3-Coder-30B's
  uncapped `ctx163k` GPQA.
- **Historical empty-answer rates under that budget are large:** GPQA
  empty counts of 91 (Gemma4-26B), 134 (A4B-QAT), 114 (Laguna), 105
  (Qwen3.8-27B) and 49 (Qwen3.6-35B), each out of 198. So historical GPQA
  largely measures finishing inside 8192 tokens.
- **Durability:** pve-tiny's nightly PBS job (12:30, `--all 1`, exclude
  910) covers CT 50013. The root disk, which holds results, has no
  `backup=0`, and the Docker disk is `backup=1`. Snapshots of 50013 were
  confirmed for 2026-09-29 and 09-30. Retention is the PBS keep-last-2.
- **Nextcloud (35.0.0) facts:**
  - Apps before this work: text, viewer, office (landing page only),
    no Tables or Collabora. The app store is reachable, and Tables 2.3.1
    (stable) supports 35.x.
  - The eval-runner container reaches
    `https://nextcloud.lab.gibbsgreatly.xyz` with valid TLS.
  - `occ app:enable` downloads and installs a missing app, not just
    enables it.
  - `occ user:auth-tokens:add -n` prints the token as its last line. That
    token has "limited capabilities" (no login password) but works for
    WebDAV (207) and the Tables API (200).
  - Tables auto-creates a "Welcome to Nextcloud Tables!" table per user on
    first use.
- **Tables 2.3 API, verified live and from its PHP source:**
  - Rows: `POST /tables/{id}/rows {"data": {colId: value}}`;
    `PUT /rows/{id}`; rows come back as `[{columnId, value}]`.
  - View settings (`PUT /views/{id}`) need real arrays:
    `columnSettings [{columnId, order}]`, `filter
    [[{columnId, operator, value}]]` (operator from `FilterOperator`, for
    example `is-equal`), `sort [{columnId, mode: ASC|DESC}]`. The
    deprecated `columns` key given as a JSON string gives HTTP 500.
  - The table's own column order and sort are only settable through OCS
    v2 `PUT /ocs/v2.php/apps/tables/api/2/tables/{id}`.
- **Wrapper:** `ai-services-stack` is on `pve-tiny`, so deploys use
  `./with-secrets-prod-tiny`. `nextcloud-stack` is on `pve`, so its
  deploys use `./with-secrets-prod`.

## Steps

Write order matters for secrets. After `eval-runner-01` lands, every
`./with-secrets*` load on the branch fails closed until the operator has
written the `HF_TOKEN` value. Do not deploy in between.

### eval-runner-01-manifest-hf-token

```yaml
id: eval-runner-01-manifest-hf-token
title: Declare HF_TOKEN in the secrets manifest
depends_on: []

change: >
  In secrets/manifest.json, in the "shared/external-apis" entry's "fields"
  list, replace the exact text "GREYNOISE_API_KEY", "MCP_GITHUB_TOKEN"
  with "GREYNOISE_API_KEY", "HF_TOKEN", "MCP_GITHUB_TOKEN" (one
  insertion, alphabetical position, same quoting and spacing). Change
  nothing else in the file.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any other edit to secrets/manifest.json"
    - "Running ./with-secrets*, openbao_write.py, provision.sh or ansible-playbook"

gates:
  - id: only-hf-token-added
    cmd: "python3 -c \"import json,subprocess; e='shared/external-apis'; new=json.load(open('secrets/manifest.json'))['entries'][e]; old=json.loads(subprocess.check_output(['git','show','stable:secrets/manifest.json']))['entries'][e]; f=new['fields']; assert f.count('HF_TOKEN')==1; f.remove('HF_TOKEN'); assert new==old; print('OK')\""
    expect: "prints OK, exit 0"
    critical: true
```

### Operator: write the HF_TOKEN value

Do this right after step 01, from your own terminal. It needs an
interactive OIDC login, which agents never get.

1. On huggingface.co, signed in, open
   <https://huggingface.co/datasets/Idavidrein/gpqa> and accept its access
   terms. They include not reposting the questions anywhere public, and
   `--log_samples` output contains them, so keep result files private.
2. Create a **read** token (Settings → Access Tokens).
3. Write it:

   ```bash
   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
   LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py shared/external-apis HF_TOKEN
   unset BAO_TOKEN
   ```

   This is the procedure from `docs/reference/secrets-management.md`
   ("Adding or rotating a secret"). It must run from this branch, because
   `openbao_write.py` refuses fields that aren't in the working tree's
   manifest.

4. Confirm the loader now resolves it (prints `set`, never the value;
   `printenv` is on the prod wrapper's read-only allowlist):

   ```bash
   ./with-secrets-prod-tiny printenv HF_TOKEN >/dev/null && echo set
   ```
### eval-runner-02-dockerfile

```yaml
id: eval-runner-02-dockerfile
title: Add the eval-runner Dockerfile
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/Dockerfile with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    # eval-runner -- lm-evaluation-harness (GPQA, IFEval) as a thin HTTP client
    # of Framework's llama-server. Built locally on ai-services-stack by
    # deploy-ai-services-stack.yml's "Install eval-runner" play and started one
    # run at a time by /usr/local/bin/eval-run -- never a long-lived compose
    # service. See docs/eval-runner/plan.md.
    FROM python:3.12-slim

    # Runs as uid 1000, not root (same convention as deep-research). The
    # playbook chowns /srv/eval-runner/results to 1000 to match, and the HF
    # cache dir is pre-created here so the named volume mounted over it
    # inherits this ownership on first mount.
    RUN useradd --create-home --uid 1000 app \
        && mkdir -p /home/app/.cache/huggingface \
        && chown -R app:app /home/app/.cache

    # Set before the RUN below, not after: nltk 3.10's import guard refuses to
    # import anything that resolves under the current working directory, and
    # the build's default cwd is / -- which contains the whole stdlib.
    WORKDIR /results

    # Pinned to the lm_eval release and API/IFEval dependency versions behind
    # every GPQA/IFEval number in docs/framework/eval-battery-phase2-plan.md,
    # so new results stay comparable with the old ones. No torch/transformers:
    # the API model path doesn't need them. Not --only-binary: langdetect,
    # rouge-score, sqlitedict and word2number only ship as sdists. openpyxl is
    # publish.py's (leaderboard.xlsx) and rapidfuzz is repobench_run.py's (edit
    # similarity), not lm_eval's.
    RUN pip install --no-cache-dir \
          "aiohttp==3.14.3" \
          "datasets==5.0.1" \
          "immutabledict==4.3.1" \
          "langdetect==1.0.9" \
          "lm_eval[api,ifeval]==0.4.12" \
          "nltk==3.10.1" \
          "openpyxl==3.1.5" \
          "rapidfuzz==3.14.6" \
          "tenacity==9.1.4"

    # Run setup (runmeta.py), scoring summary (summarize.py), Nextcloud
    # publishing (publish.py, findings.md -- copied in from docs/eval-runner/ by
    # the playbook) and the selftest pieces. Copied after the pip layer so editing them doesn't invalidate the
    # slow install. The test_*.py unit tests stay in the repo, not the image.
    COPY findings.md mock_nextcloud.py mock_openai.py publish.py repobench_run.py runmeta.py selftest.sh selftest_checks.py summarize.py wrapper_common.py wrapper_selftest.sh /opt/eval-runner/
    RUN chmod 0755 /opt/eval-runner/selftest.sh /opt/eval-runner/wrapper_selftest.sh

    USER app
    ENV HOME=/home/app
    RUN python -c "import nltk; nltk.download('punkt_tab', quiet=True)"

    ENTRYPOINT ["lm_eval"]

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/Dockerfile
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/Dockerfile | cut -d' ' -f1"
    expect: "d1412eefead159b79be2d1237fcddb26b8e551c813743703ad185b350a9f6d12"
    critical: true
```

### eval-runner-03-eval-run-script

```yaml
id: eval-runner-03-eval-run-script
title: Add the eval-run launcher script
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/eval-run with exactly this content (byte for byte, including the
  trailing newline), then run chmod 0755 on it. It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    #!/usr/bin/env bash
    # eval-run -- start, resume, self-test and summarise eval battery runs
    # (GPQA, IFEval, BFCL, AgentBench, RepoBench) against whatever model
    # Framework's llama-server is serving right now. Installed by deploy-ai-services-stack.yml's "Install eval-runner"
    # play; see docs/eval-runner/plan.md. Secrets never pass through this
    # script: containers get them only via --env-file.
    set -euo pipefail

    ENV_FILE=/etc/eval-runner/eval-runner.env
    RESULTS_DIR=/srv/eval-runner/results
    IMAGE=eval-runner:local
    BFCL_IMAGE=eval-runner-bfcl:local
    AGENTBENCH_IMAGE=eval-runner-agentbench:local
    HF_VOLUME=eval-runner-hf:/home/app/.cache/huggingface
    DOCKER_SOCK=/var/run/docker.sock

    usage() {
      cat <<'USAGE'
    Usage: eval-run <gpqa|ifeval> [--pilot] [--concurrency N] [--max-gen-toks N] [--note TEXT]
           eval-run <bfcl|agentbench|repobench> [--pilot] [--note TEXT]
           eval-run resume <run> [--force]
           eval-run selftest
           eval-run results [run...]
           eval-run publish [--dry-run]

    gpqa|ifeval  Start one detached run (container eval-<run>) against the model
                 Framework's llama-server is serving. Uses Framework's GPU for
                 hours -- check nothing else needs it first.
    bfcl         BFCL v3 "simple" (400 cases, bfcl-eval 2025.8.6.2), as every
                 historical BFCL number.
    agentbench   AgentBench os-std, 100 episodes sampled with seed 42, as the
                 historical numbers. Each episode runs in a throwaway sandbox
                 container on this CT's Docker, with networking disabled.
    repobench    RepoBench (rebuilt): Python v1.1, 3 settings x 5 context
                 levels. A new series; the historical RepoBench numbers came
                 from scripts that are lost, so they aren't comparable.
      --pilot          a small sample instead of the full task: 40 examples
                       (gpqa/ifeval/bfcl), 10 episodes (agentbench), 5 per
                       level and setting (repobench)
      --concurrency N  parallel requests (gpqa/ifeval only; default 1, as every
                       historical result)
      --max-gen-toks N token budget per answer (default 8192, the budget every
                       comparable result used). A larger one, e.g. 32768, starts
                       a separate series (run name gets -32k), ranked only
                       against runs at the same budget. Expect several times
                       the 8192 run's duration.
      --note TEXT      stored in run.json. Use it for server settings the API
                       can't show, e.g. "reasoning_effort=high"
    resume       Re-run an interrupted run. Answers already received are
                 replayed from its cache. Refuses if the server's fingerprint
                 (model, build, sampling defaults, chat template) has changed,
                 unless --force.
    selftest     Exercise the whole harness against a stand-in server inside
                 each image -- GPQA/IFEval and publishing, then BFCL, AgentBench
                 (two real sandbox episodes) and RepoBench (no Framework, no
                 GPU). Exits non-zero on failure.
    results      Headline scores and response-quality flags per run.
    publish      Push everything (eval-runner runs + historical) to Nextcloud:
                 Reports/eval-runner/ (leaderboard.xlsx/.md, findings.md, one
                 report.md + manifest.json per run) and the Tables table
                 "Model evaluations" (rows upserted, never duplicated).
                 --dry-run renders into ${RESULTS_DIR}/_publish-preview instead.
    USAGE
    }

    die() {
      echo "eval-run: $*" >&2
      exit 2
    }

    # Run a short helper container (runmeta.py / summarize.py) in the foreground.
    helper() {
      docker run --rm --env-file "$ENV_FILE" -v "${RESULTS_DIR}:/results" \
        --entrypoint python "$IMAGE" "$@"
    }

    refuse_if_running() {
      local running
      running=$(docker ps --filter 'name=^eval-' --format '{{.Names}}')
      if [[ -n "$running" ]]; then
        echo "eval-run: an eval is already running: $running" >&2
        exit 1
      fi
    }

    # image_args <task>: the image (and, for agentbench, the Docker socket its
    # task server starts sandboxes through) a run of <task> needs.
    image_args() {
      case "$1" in
        bfcl) echo "$BFCL_IMAGE" ;;
        agentbench)
          echo "-v ${DOCKER_SOCK}:${DOCKER_SOCK} --group-add $(stat -c %g "$DOCKER_SOCK") $AGENTBENCH_IMAGE"
          ;;
        *) echo "$IMAGE" ;;
      esac
    }

    launch() {
      local run="$1" task="$2"
      local -a image
      read -r -a image <<<"$(image_args "$task")"
      docker run -d --name "eval-${run}" \
        --env-file "$ENV_FILE" \
        -v "${RESULTS_DIR}:/results" \
        -v "$HF_VOLUME" \
        --entrypoint python \
        "${image[@]}" /opt/eval-runner/runmeta.py exec "/results/${run}" >/dev/null
      echo "Started eval-${run}"
      echo "  follow:  docker logs -f eval-${run}"
      echo "  scores:  eval-run results ${run}"
      echo "  resume:  eval-run resume ${run}   (if it's interrupted)"
      echo "  cleanup: docker rm eval-${run}   (after it exits)"
    }

    valid_run_name() {
      [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]] && [[ -f "${RESULTS_DIR}/$1/run.json" ]]
    }

    cmd_start() {
      local short="$1"
      shift
      local -a extra=()
      local concurrency=1 note="" max_gen_toks=8192
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --pilot) extra+=(--pilot); shift ;;
          --concurrency) concurrency="${2:?--concurrency needs a value}"; shift 2 ;;
          --max-gen-toks) max_gen_toks="${2:?--max-gen-toks needs a value}"; shift 2 ;;
          --note) note="${2?--note needs a value}"; shift 2 ;;
          *) usage >&2; exit 2 ;;
        esac
      done
      [[ "$concurrency" =~ ^[1-9][0-9]*$ ]] || die "--concurrency must be a positive integer"
      if [[ "$short" != gpqa && "$short" != ifeval && "$concurrency" != 1 ]]; then
        die "--concurrency only applies to gpqa/ifeval"
      fi
      [[ "$max_gen_toks" =~ ^[1-9][0-9]*$ ]] || die "--max-gen-toks must be a positive integer"
      refuse_if_running

      local run
      run=$(helper /opt/eval-runner/runmeta.py start --task "$short" "${extra[@]}" \
        --concurrency "$concurrency" --max-gen-toks "$max_gen_toks" --note "$note")
      launch "$run" "$short"
      if [[ -z "$note" ]]; then
        echo "  note:    no --note given; server-side chat-template kwargs (reasoning effort etc.) are not recorded"
      fi
    }

    cmd_resume() {
      local run="${1:-}" force=0
      [[ -n "$run" ]] || die "resume needs a run name (see: ls ${RESULTS_DIR})"
      shift
      if [[ "${1:-}" == "--force" ]]; then
        force=1
        shift
      fi
      [[ $# -eq 0 ]] || die "unexpected arguments: $*"
      valid_run_name "$run" || die "no run named '$run' under ${RESULTS_DIR}"
      refuse_if_running

      local rc=0
      helper /opt/eval-runner/runmeta.py check "/results/${run}" || rc=$?
      if [[ $rc -eq 3 && $force -eq 0 ]]; then
        die "server changed since this run started; resuming would mix answers from two configurations (use --force to override)"
      elif [[ $rc -ne 0 && $rc -ne 3 ]]; then
        die "could not check the server (exit $rc)"
      fi
      docker rm "eval-${run}" >/dev/null 2>&1 || true
      launch "$run" "$(helper /opt/eval-runner/runmeta.py field "/results/${run}" task)"
    }

    [[ $# -ge 1 ]] || { usage >&2; exit 2; }
    case "$1" in
      gpqa|ifeval|bfcl|agentbench|repobench)
        cmd_start "$@"
        ;;
      resume)
        shift
        cmd_resume "$@"
        ;;
      selftest)
        [[ $# -eq 1 ]] || { usage >&2; exit 2; }
        stamp=$(date -u +%Y%m%dT%H%M%SZ)
        selftest_in() {
          local -a image
          read -r -a image <<<"$(image_args "$1")"
          shift
          docker run --rm \
            --env-file "$ENV_FILE" \
            -e "SELFTEST_RUN=$stamp" \
            -v "${RESULTS_DIR}:/results" \
            -v "$HF_VOLUME" \
            --entrypoint /bin/sh \
            "${image[@]}" "$@"
        }
        # GPQA/IFEval + publishing, then each wrapper: <limit> <expected requests>
        # (bfcl and agentbench: one request per case/episode; repobench: one per
        # setting x level).
        selftest_in gpqa /opt/eval-runner/selftest.sh
        selftest_in bfcl /opt/eval-runner/wrapper_selftest.sh bfcl 2 2
        selftest_in agentbench /opt/eval-runner/wrapper_selftest.sh agentbench 2 2
        selftest_in repobench /opt/eval-runner/wrapper_selftest.sh repobench 1 15
        echo "all selftests OK"
        ;;
      results)
        shift
        targets=()
        for name in "$@"; do
          [[ "$name" =~ ^[A-Za-z0-9_.-]+$ ]] || die "bad run name '$name'"
          targets+=("/results/${name}")
        done
        exec docker run --rm \
          -v "${RESULTS_DIR}:/results:ro" \
          --entrypoint python \
          "$IMAGE" /opt/eval-runner/summarize.py "${targets[@]}"
        ;;
      publish)
        shift
        if [[ "${1:-}" == "--dry-run" ]]; then
          [[ $# -eq 1 ]] || die "unexpected arguments: $*"
          rm -rf "${RESULTS_DIR}/_publish-preview"
          helper /opt/eval-runner/publish.py --dry-run /results/_publish-preview
          echo "preview: ${RESULTS_DIR}/_publish-preview/"
        else
          [[ $# -eq 0 ]] || die "unexpected arguments: $*"
          helper /opt/eval-runner/publish.py
        fi
        ;;
      -h|--help)
        usage
        ;;
      *)
        usage >&2
        exit 2
        ;;
    esac

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/eval-run
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/eval-run | cut -d' ' -f1"
    expect: "3c349c4827bf5fea0845b1a943557414160a38a830a2a54723ec30b9692331ee"
    critical: true
  - id: executable
    cmd: "test -x terraform/lxc/ansible/files/eval-runner/eval-run && echo OK"
    expect: "OK"
    critical: true
  - id: shellcheck
    cmd: "shellcheck terraform/lxc/ansible/files/eval-runner/eval-run"
    expect: "no output, exit 0"
    critical: true
```

### eval-runner-06a-mock-server

```yaml
id: eval-runner-06a-mock-server
title: Add the selftest stand-in server
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/mock_openai.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Minimal OpenAI-compatible stand-in for `eval-run selftest`.

    Answers every chat completion with one fixed reply, so the whole lm_eval
    pipeline (gated dataset download, request/response handling, scoring,
    result files, response cache) -- and the BFCL, AgentBench and RepoBench
    wrappers -- can be exercised without touching Framework's GPU. A request
    carrying "tools" gets a tool call to the first tool instead (BFCL).
    /v1/completions (raw text, RepoBench) answers with the same reply, and
    /tokenize counts ~4 characters per token. Listens on 127.0.0.1 only, inside the selftest container.

    Environment:
      MOCK_PORT          listen port (default 18080)
      MOCK_MODEL         model id served on /v1/models (default selftest-mock)
      MOCK_MODEL_PATH    model_path reported on /props -- change it to make a
                         second instance look like a different server
      MOCK_REQUEST_LOG   if set, append every (chat) completion request body as
                         one JSON line (selftest asserts on what lm_eval sent)
      MOCK_EMPTY_EVERY   if N > 0, every Nth reply has empty content (the
                         "reasoning ate the token budget" failure shape), so
                         the empty-response flags can be checked
      MOCK_REPLY         the fixed reply text (default: a GPQA-style answer)
    """

    import json
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    PORT = int(os.environ.get("MOCK_PORT", "18080"))
    MODEL = os.environ.get("MOCK_MODEL", "selftest-mock")
    MODEL_PATH = os.environ.get("MOCK_MODEL_PATH", "/models/selftest-mock.gguf")
    REQUEST_LOG = os.environ.get("MOCK_REQUEST_LOG", "")
    EMPTY_EVERY = int(os.environ.get("MOCK_EMPTY_EVERY", "0"))
    REPLY = os.environ.get("MOCK_REPLY", "Let me think step by step. The answer is (A).")

    PROPS = {
        "model_path": MODEL_PATH,
        "model_alias": MODEL,
        "build_info": "selftest-mock",
        "total_slots": 1,
        "chat_template": "{{ messages }}",
        "default_generation_settings": {
            # Big enough for runmeta's context check at the default budget.
            "n_ctx": 32768,
            "params": {"temperature": 1.0, "top_p": 0.95, "min_p": 0.01, "n_predict": -1},
        },
    }

    _lock = threading.Lock()
    _count = 0


    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.rstrip("/")
            if path == "/v1/models":
                self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
            elif path == "/props":
                self._send(200, PROPS)
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            global _count
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            path = self.path.rstrip("/")
            if path == "/tokenize":
                content = json.loads(raw).get("content", "")
                self._send(200, {"tokens": [0] * (len(content) // 4)})
                return
            if path not in ("/v1/chat/completions", "/v1/completions"):
                self._send(404, {"error": "not found"})
                return
            with _lock:
                _count += 1
                n = _count
                if REQUEST_LOG:
                    with open(REQUEST_LOG, "a") as fh:
                        fh.write(json.dumps(json.loads(raw)) + "\n")
            content = "" if EMPTY_EVERY > 0 and n % EMPTY_EVERY == 0 else REPLY
            if path == "/v1/completions":
                self._send(200, {"id": f"selftest-{n}", "object": "text_completion", "model": MODEL,
                                 "choices": [{"index": 0, "finish_reason": "stop", "text": content}],
                                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
                return
            message = {"role": "assistant", "content": content}
            tools = json.loads(raw).get("tools") if raw else None
            if tools and content:
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"call-{n}", "type": "function",
                    "function": {"name": tools[0]["function"]["name"], "arguments": "{}"},
                }]}
            self._send(200, {
                "id": f"selftest-{n}",
                "object": "chat.completion",
                "model": MODEL,
                "choices": [{
                    "index": 0,
                    "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                    "message": message,
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })

        def log_message(self, *args):
            """Silence per-request access logging; lm_eval's own log is enough."""


    if __name__ == "__main__":
        # Plain HTTP on loopback inside a throwaway test container -- nothing
        # leaves 127.0.0.1, and lm_eval talks to real servers over the same scheme.
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()  # NOSONAR

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/mock_openai.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/mock_openai.py | cut -d' ' -f1"
    expect: "3ec3df4f26dbd71ca032b7e9f71fbb896dc94cafdef529b90d634f4787cb63b0"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/mock_openai.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-06b-selftest-script

```yaml
id: eval-runner-06b-selftest-script
title: Add the in-image selftest script
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/selftest.sh with exactly this content (byte for byte, including the
  trailing newline), then run chmod 0755 on it. It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    #!/bin/sh
    # eval-runner self-test, run inside the eval-runner image by
    # `eval-run selftest` (and by the deploy, as a gate). Uses the same
    # runmeta.py start/exec/check path as a real run, against mock_openai.py
    # instead of Framework -- no GPU. Proves, in order:
    #   1. a run (both tasks, --limit 2) completes: gated GPQA download
    #      (HF_TOKEN), IFEval nltk data, scoring, result files
    #   2. every request carried max_tokens 8192, temperature 0, seed 1234 and
    #      the served model id; empty-response flags count correctly
    #   3. resume: re-running the same run sends zero new requests (cache)
    #   4. `runmeta check` passes against the same server and exits 3 against
    #      a server that reports a different model_path
    #   5. publish (the real HTTP client) to mock_nextcloud.py twice: report
    #      files, one table with all columns and views, rows upserted without
    #      duplicates, the share, and no samples files uploaded
    # Scores are meaningless (canned replies).
    set -eu

    d=/opt/eval-runner
    root=/results/_selftest
    log=/tmp/selftest-requests.jsonl
    pids=""
    cleanup() {
      for pid in $pids; do
        kill "$pid" 2>/dev/null || true
      done
    }
    trap cleanup EXIT

    start_mock() {
      MOCK_PORT="$1" MOCK_MODEL_PATH="$2" MOCK_REQUEST_LOG="$log" MOCK_EMPTY_EVERY=2 \
        python "$d/mock_openai.py" &
      pids="$pids $!"
      i=0
      until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$1/v1/models', timeout=1)" 2>/dev/null; do
        i=$((i + 1))
        if [ "$i" -ge 50 ]; then
          echo "selftest FAILED: mock server on :$1 did not start" >&2
          exit 1
        fi
        sleep 0.2
      done
    }

    # Keep only the 5 most recent selftest runs (~140 KB each; one per deploy).
    # Names end in a UTC stamp, so a reverse name sort is newest-first.
    mkdir -p "$root"
    find "$root" -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n +5 | while read -r old; do
      rm -rf "$old"
    done

    rm -f "$log"
    export OPENAI_API_KEY=selftest
    start_mock 18080 /models/selftest-mock.gguf

    echo "== 1. run both tasks at --limit 2 against the mock"
    run=$(python "$d/runmeta.py" start --base-url http://127.0.0.1:18080 --task both --limit 2 \
      --results-root "$root" --stamp "${SELFTEST_RUN:?SELFTEST_RUN must be set}" --note selftest)
    dir="$root/$run"
    python "$d/runmeta.py" exec "$dir"

    echo "== 2. request settings and response flags"
    python "$d/selftest_checks.py" --requests "$log" --expect-requests 4 --model selftest-mock \
      --run-dir "$dir" --expect-empty 2
    python "$d/summarize.py" --check "$dir"

    echo "== 3. resume replays from cache (no new requests)"
    python "$d/runmeta.py" check "$dir"
    python "$d/runmeta.py" exec "$dir"
    python "$d/selftest_checks.py" --requests "$log" --expect-requests 4 --model selftest-mock

    echo "== 4. a changed server is detected"
    start_mock 18081 /models/some-other-model.gguf
    set +e
    python "$d/runmeta.py" check "$dir" --base-url http://127.0.0.1:18081
    rc=$?
    set -e
    if [ "$rc" -ne 3 ]; then
      echo "selftest FAILED: runmeta check returned $rc for a changed server, want 3" >&2
      exit 1
    fi

    echo "== 5. publish to a stand-in Nextcloud, twice (no duplicates)"
    MOCK_NC_PORT=18090 python "$d/mock_nextcloud.py" &
    pids="$pids $!"
    i=0
    until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18090/_mock/state', timeout=1)" 2>/dev/null; do
      i=$((i + 1))
      if [ "$i" -ge 50 ]; then
        echo "selftest FAILED: mock Nextcloud did not start" >&2
        exit 1
      fi
      sleep 0.2
    done
    pubroot=$(mktemp -d)
    cp -r "$dir" "$pubroot/"
    for _ in 1 2; do
      NEXTCLOUD_EVAL_REPORTS_URL=http://127.0.0.1:18090 NEXTCLOUD_EVAL_REPORTS_USER=eval-reports \
        NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD=selftest NEXTCLOUD_EVAL_TABLE_SHARE_WITH=steve \
        python "$d/publish.py" --results-root "$pubroot"
    done
    python "$d/selftest_checks.py" --nextcloud-state http://127.0.0.1:18090/_mock/state \
      --expect-rows 2 --published-run "$run"
    rm -rf "$pubroot"

    echo "selftest OK"

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/selftest.sh
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/selftest.sh | cut -d' ' -f1"
    expect: "69f3263782fad1713d2216bd773f502ee182291066990fa5559abbc00a86c731"
    critical: true
  - id: shellcheck
    cmd: "shellcheck -s sh terraform/lxc/ansible/files/eval-runner/selftest.sh"
    expect: "no output, exit 0"
    critical: true
```

### eval-runner-06c-summarize

```yaml
id: eval-runner-06c-summarize
title: Add the results summariser
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/summarize.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Print headline numbers for eval-run result directories.

    Tasks: GPQA and IFEval (lm_eval), and BFCL, AgentBench and RepoBench
    (eval-runner's own wrappers -- bfcl_run.py, agentbench_run.py,
    repobench_run.py -- which write lm_eval-shaped results_*.json files, with
    their comparability decided by the wrapper under config.eval_runner).

    With no arguments, summarises every run directory under /results except
    those starting with "_" (selftest output). With --check, exits non-zero
    unless every given directory holds results for each of its run.json
    tasks (GPQA and IFEval if there's no run.json) with numeric headline
    metrics -- the selftest uses this as one of its checks.

    Each task also gets response-quality flags read from its samples file,
    counted per question:
      empty     the raw response was empty -- typically a reasoning model that
                used its whole token budget thinking, so the answer never came
      unparsed  (GPQA only) flexible-extract found no answer letter
    Treat a score with many of either as an infrastructure/config problem to
    inspect, not as the model's capability. (Deliberately no "accuracy on
    answered questions" figure: the questions a model finishes inside the
    token budget skew easy, and differ per model, so it isn't comparable.)

    Historical results (the Ollama-era runs on framework, imported once into
    /results/_historical/<source-dir>/) are listed in a second section. Only
    results that are comparable with eval-runner's are shown: full runs
    (no --limit) with max_gen_toks=8192. Everything else is listed as
    excluded, with the reason (pilot, the Bug 6 missing token cap, or a
    different token budget).

    Token budget series: a full run at a larger max_gen_toks (eval-run
    --max-gen-toks, e.g. 32768) is a separate series. (Smaller budgets are
    treated like Bug 6: truncation, not a series.) It is ranked only
    against other runs at the same budget, never against the 8192 series --
    a bigger budget lets reasoning models finish answers they'd otherwise
    lose, so the scores measure something different.
    """

    import argparse
    import glob
    import json
    import os
    import sys

    RESULTS_ROOT = "/results"
    HISTORICAL_DIR = "_historical"
    MAX_GEN_TOKS = 8192

    HEADLINE = {
        "gpqa_diamond_cot_zeroshot": [
            ("GPQA flex", "exact_match,flexible-extract"),
            ("GPQA strict", "exact_match,strict-match"),
        ],
        "ifeval": [
            ("IFEval p-strict", "prompt_level_strict_acc,none"),
            ("IFEval p-loose", "prompt_level_loose_acc,none"),
        ],
        "bfcl_simple": [("BFCL simple", "accuracy,none")],
        "agentbench_os_std": [("AgentBench os-std", "success_rate,none")],
        "repobench_python": [
            ("RepoBench EM", "exact_match,weighted"),
            ("RepoBench ES", "edit_similarity,weighted"),
        ],
    }
    # Tasks scored by lm_eval itself (samples_*.jsonl, gen_kwargs comparability).
    LM_EVAL_TASKS = ("gpqa_diamond_cot_zeroshot", "ifeval")
    # The series each task's comparable (ranked) results belong to. The
    # wrappers write these names into config.eval_runner.series.
    STANDARD_SERIES = {
        "gpqa_diamond_cot_zeroshot": "8k",
        "ifeval": "8k",
        "bfcl_simple": "v3 simple",
        "agentbench_os_std": "100 seeded",
        "repobench_python": "rebuilt",
    }


    def _results_stamp(path):
        """results_<stamp>.json -> <stamp>, shared with that run's samples files."""
        return os.path.basename(path)[len("results_"):-len(".json")]


    def _max_gen_toks(gen_kwargs):
        """lm_eval records gen_kwargs as a dict or as a 'k=v,k=v' string."""
        if isinstance(gen_kwargs, dict):
            value = gen_kwargs.get("max_gen_toks")
        else:
            pairs = dict(part.split("=", 1) for part in str(gen_kwargs or "").split(",") if "=" in part)
            value = pairs.get("max_gen_toks")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


    def exclusion_reason(data):
        """None if a results file is comparable with eval-runner runs, else why not."""
        config = data.get("config", {})
        wrapper = config.get("eval_runner")
        if wrapper is not None and config.get("limit") is None:
            return wrapper.get("exclusion")
        if config.get("limit") is not None:
            return f"pilot (limit {config['limit']:g})" if isinstance(config["limit"], (int, float)) else "pilot"
        budget = _max_gen_toks(config.get("gen_kwargs"))
        if budget is None or budget < MAX_GEN_TOKS:
            return f"no max_gen_toks={MAX_GEN_TOKS} (Bug 6 truncation risk)"
        if budget != MAX_GEN_TOKS:
            return f"token budget {budget} (separate {series_label(budget)} series)"
        return None


    def series_label(budget):
        """8192 -> '8k', 32768 -> '32k', other values unchanged."""
        return f"{budget // 1024}k" if budget % 1024 == 0 else str(budget)


    def series(data):
        """The token-budget series a results file is ranked in ('8k', '32k', ...),
        or None for pilots and runs without a token cap."""
        config = data.get("config", {})
        if config.get("limit") is not None:
            return None
        if config.get("eval_runner") is not None:
            return config["eval_runner"].get("series")
        budget = _max_gen_toks(config.get("gen_kwargs"))
        if budget is None or budget < MAX_GEN_TOKS:
            return None
        return series_label(budget)


    def model_name(data):
        model_args = data.get("config", {}).get("model_args")
        if isinstance(model_args, dict):
            return model_args.get("model")
        pairs = dict(part.split("=", 1) for part in str(model_args or "").split(",") if "=" in part)
        return pairs.get("model")


    def load(run_dir, comparable_only=False):
        """Map task -> {metrics, n, samples, model}, the newest results file winning.

        With comparable_only, results files failing exclusion_reason() are skipped.
        """
        found = {}
        pattern = os.path.join(run_dir, "**", "results_*.json")
        for path in sorted(glob.glob(pattern, recursive=True)):
            with open(path) as fh:
                data = json.load(fh)
            if comparable_only and exclusion_reason(data):
                continue
            stamp = _results_stamp(path)
            for task, metrics in data.get("results", {}).items():
                if task in HEADLINE:
                    samples = os.path.join(os.path.dirname(path), f"samples_{task}_{stamp}.jsonl")
                    found[task] = {
                        "metrics": metrics,
                        "n": data.get("n-samples", {}).get(task, {}).get("effective"),
                        "samples": samples if os.path.exists(samples) else None,
                        "model": model_name(data),
                    }
        return found


    def response_flags(samples_path, task):
        """Count empty (and, for GPQA, unparsed) responses per question."""
        empty_by_doc = {}
        unparsed = set()
        with open(samples_path) as fh:
            for line in fh:
                row = json.loads(line)
                doc = row["doc_id"]
                resps = row.get("resps") or [[""]]
                raw = resps[0][0] if resps[0] else ""
                empty_by_doc[doc] = not str(raw).strip()
                if (task.startswith("gpqa") and row.get("filter") == "flexible-extract"
                        and (row.get("filtered_resps") or [None])[0] == "[invalid]"):
                    unparsed.add(doc)
        return {
            "questions": len(empty_by_doc),
            "empty": sum(empty_by_doc.values()),
            "unparsed": len(unparsed) if task.startswith("gpqa") else None,
        }


    def task_flags(task, metrics, samples):
        """Response-quality flags for one task: from lm_eval's samples file, or
        (wrapper tasks) from the empty/errors counts the wrapper recorded.
        None if neither is available."""
        if task in LM_EVAL_TASKS:
            return response_flags(samples, task) if samples else None
        if "empty,none" not in metrics:
            return None
        return {"questions": None, "empty": metrics.get("empty,none"), "unparsed": None,
                "errors": metrics.get("errors,none")}


    def _flag_text(task, entry):
        flags = task_flags(task, entry["metrics"], entry["samples"])
        if flags is None:
            return "[no samples file]"
        text = f"empty {flags['empty']}"
        if flags["unparsed"] is not None:
            text += f", unparsed {flags['unparsed']}"
        if flags.get("errors"):
            text += f", errors {flags['errors']}"
        if flags["empty"] or flags["unparsed"] or flags.get("errors"):
            text += " <- inspect samples"
        return f"[{text}]"


    def task_parts(task, entry):
        """Formatted metrics + flags for one task; ok is False on a non-numeric metric."""
        parts = []
        ok = True
        for label, key in HEADLINE[task]:
            value = entry["metrics"].get(key)
            if isinstance(value, (int, float)):
                parts.append(f"{label} {value * 100:.2f}%")
            else:
                parts.append(f"{label} ?")
                ok = False
        parts.append(f"n={entry['n']}")
        parts.append(_flag_text(task, entry))
        return parts, ok


    def _expected_tasks(run_dir):
        """Tasks a run should have results for: run.json's list, or GPQA+IFEval."""
        try:
            with open(os.path.join(run_dir, "run.json")) as fh:
                return json.load(fh).get("tasks") or list(LM_EVAL_TASKS)
        except (OSError, ValueError):
            return list(LM_EVAL_TASKS)


    def describe(run_dir, check, comparable_only=False):
        """Return (line, ok) for one run directory."""
        name = os.path.basename(os.path.normpath(run_dir))
        found = load(run_dir, comparable_only=comparable_only)
        if not found:
            return f"{name}: no results yet (still running, or failed)", False
        ok = True
        parts = []
        expected = _expected_tasks(run_dir)
        for task in HEADLINE:
            if task not in found:
                ok = ok and not (check and task in expected)
                continue
            task_text, task_ok = task_parts(task, found[task])
            parts += task_text
            ok = ok and task_ok
        return f"{name}: " + ", ".join(parts), ok


    def historical_lines(root):
        """Comparable historical results first, then one line per excluded result."""
        hist_root = os.path.join(root, HISTORICAL_DIR)
        if not os.path.isdir(hist_root):
            return []
        lines = ["", f"historical (imported from framework; comparable = full run, max_gen_toks={MAX_GEN_TOKS}):"]
        excluded = []
        for source in sorted(d for d in glob.glob(os.path.join(hist_root, "*")) if os.path.isdir(d)):
            found = load(source, comparable_only=True)
            if found:
                line, _ = describe(source, check=False, comparable_only=True)
                model = next((e["model"] for e in found.values() if e["model"]), None)
                lines.append(f"  {line}" + (f"  ({model})" if model else ""))
            for path in sorted(glob.glob(os.path.join(source, "**", "results_*.json"), recursive=True)):
                with open(path) as fh:
                    data = json.load(fh)
                reason = exclusion_reason(data)
                tasks = [t for t in data.get("results", {}) if t in HEADLINE]
                line = f"  {os.path.basename(source)} {','.join(tasks)}: {reason}"
                if reason and tasks and line not in excluded:
                    excluded.append(line)
        if excluded:
            lines.append("excluded:")
            lines.extend(excluded)
        return lines


    def main(argv=None):
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--check", action="store_true")
        parser.add_argument("dirs", nargs="*")
        args = parser.parse_args(argv)

        if not args.dirs:
            dirs = sorted(
                d for d in glob.glob(os.path.join(RESULTS_ROOT, "*"))
                if os.path.isdir(d) and not os.path.basename(d).startswith("_")
            )
            if not dirs:
                print("no runs yet")
            for run_dir in dirs:
                print(describe(run_dir, check=False)[0])
            for line in historical_lines(RESULTS_ROOT):
                print(line)
            return 0
        dirs = args.dirs

        all_ok = True
        for run_dir in dirs:
            line, ok = describe(run_dir, args.check)
            print(line)
            all_ok = all_ok and ok

        if args.check:
            if not all_ok:
                print("check FAILED: missing task or non-numeric headline metric", file=sys.stderr)
                return 1
            print("check OK")
        return 0


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/summarize.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/summarize.py | cut -d' ' -f1"
    expect: "a02fc3ec621fa971e12300a16fe0d9065e6f9537815c3b8ecb6caf4085c081dc"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/summarize.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-06d-runmeta

```yaml
id: eval-runner-06d-runmeta
title: Add run setup (fingerprint, naming, lm_eval argv)
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/runmeta.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Run setup for eval-runner: server fingerprint, run naming, lm_eval argv.

    Subcommands (run inside the eval-runner image by eval-run / selftest.sh):

      start  Snapshot the server, choose the run name, create
             <results-root>/<run>/run.json (server fingerprint plus the exact
             lm_eval argv) and print the run name.
      exec   Replace this process with lm_eval, using the argv in run.json.
             Starting and resuming a run both go through here, so a resume
             repeats exactly the same command. lm_eval's --use_cache commits
             every response as it arrives, so a resumed run only sends the
             requests the interrupted one never finished.
      check  Re-snapshot the server and compare with run.json's fingerprint.
             Exits 3 if it changed, so `eval-run resume` refuses to mix
             answers from two different server configurations.

    Server-side chat-template kwargs (for example llama-server's
    --chat-template-kwargs '{"reasoning_effort":"high"}') are not visible
    over the API, so they cannot be part of the fingerprint. Record them with
    --note.

    --max-gen-toks (default 8192, the budget every comparable result used)
    starts a separate token-budget series: the run name gets a -32k style
    suffix and summarize.py ranks it only against runs at the same budget.
    `start` refuses a budget the server's per-slot context can't hold.
    """

    import argparse
    import datetime
    import hashlib
    import json
    import os
    import re
    import sys
    import urllib.request

    TASKS = {
        "gpqa": ["gpqa_diamond_cot_zeroshot"],
        "ifeval": ["ifeval"],
        "both": ["gpqa_diamond_cot_zeroshot", "ifeval"],
        "bfcl": ["bfcl_simple"],
        "agentbench": ["agentbench_os_std"],
        "repobench": ["repobench_python"],
    }
    # Which program runs each task: lm_eval itself, or eval-runner's wrapper
    # /opt/eval-runner/<harness>_run.py (in the harness's own image for bfcl
    # and agentbench -- see eval-run).
    HARNESS = {"gpqa": "lm_eval", "ifeval": "lm_eval", "both": "lm_eval",
               "bfcl": "bfcl", "agentbench": "agentbench", "repobench": "repobench"}
    PILOT_LIMIT = 40
    # --pilot sizes for the wrappers: test cases (bfcl), episodes (agentbench),
    # samples per context-length level and setting (repobench).
    WRAPPER_PILOT_LIMITS = {"bfcl": 40, "agentbench": 10, "repobench": 5}
    MAX_GEN_TOKS = 8192
    # Per-answer token budget each wrapper uses: BFCL's historical handler never
    # set max_tokens (server default); AgentBench's agent config used 3072;
    # RepoBench (rebuilt) is a raw completion of one line, 128 tokens as
    # upstream RepoBench.
    WRAPPER_MAX_GEN_TOKS = {"bfcl": None, "agentbench": 3072, "repobench": 128}
    REQUEST_TIMEOUT = 3600
    # Seconds per generated token allowed on top of REQUEST_TIMEOUT's floor:
    # 32768 tokens at the slowest decode seen on framework (~10 tok/s) needs
    # well over an hour.
    SECONDS_PER_TOKEN = 0.15
    # Prompt tokens the per-slot context must hold beyond max_gen_toks (GPQA's
    # longest prompt with the chat template is well under 1k tokens).
    PROMPT_HEADROOM = 2048
    # The same for the wrappers: BFCL simple and AgentBench prompts are short
    # (AgentBench's 8-round history stays under ~6k); RepoBench prompts are
    # cut to 15800 tokens, as upstream.
    WRAPPER_PROMPT_HEADROOM = {"bfcl": 4096, "agentbench": 8192, "repobench": 16384}
    PROPS_TOP = ("model_path", "model_alias", "build_info", "total_slots")
    PROPS_PARAMS = (
        "temperature", "top_k", "top_p", "min_p", "n_predict", "seed",
        "reasoning_format", "chat_format", "samplers",
    )
    # Recorded in run.json, but not part of the fingerprint: they don't change
    # what the model answers.
    NOT_FINGERPRINTED = ("base_url", "total_slots")
    EXIT_CHANGED = 3


    def _get_json(url, api_key, timeout=10):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)


    def snapshot_server(base_url, api_key, get_json=None):
        """What the server exposes about the model it is serving."""
        get_json = get_json or _get_json
        models = get_json(f"{base_url}/v1/models", api_key)
        model_id = models["data"][0]["id"]
        if "," in model_id:
            raise ValueError(f"model id {model_id!r} contains a comma, which lm_eval's --model_args can't carry")
        try:
            props = get_json(f"{base_url}/props", api_key)
        except Exception:  # not llama-server, or /props disabled
            props = None

        server = {"base_url": base_url, "model_id": model_id, "props": None}
        if props is not None:
            settings = props.get("default_generation_settings", {})
            params = settings.get("params", {})
            server["props"] = {
                **{key: props.get(key) for key in PROPS_TOP},
                "n_ctx": settings.get("n_ctx"),
                "params": {key: params.get(key) for key in PROPS_PARAMS},
                "chat_template_sha256": hashlib.sha256(
                    (props.get("chat_template") or "").encode()
                ).hexdigest(),
            }
        return server


    def _fingerprint_view(server):
        view = {k: v for k, v in server.items() if k not in NOT_FINGERPRINTED}
        if view.get("props"):
            view["props"] = {k: v for k, v in view["props"].items() if k not in NOT_FINGERPRINTED}
        return view


    def fingerprint(server):
        canonical = json.dumps(_fingerprint_view(server), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


    def _flatten(value, prefix=""):
        if isinstance(value, dict):
            out = {}
            for key, sub in value.items():
                out.update(_flatten(sub, f"{prefix}{key}."))
            return out
        return {prefix.rstrip("."): value}


    def server_changes(old, new):
        """Human-readable differences between two snapshots' fingerprinted fields."""
        a = _flatten(_fingerprint_view(old))
        b = _flatten(_fingerprint_view(new))
        return [f"{key}: {a.get(key)!r} -> {b.get(key)!r}" for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)]


    def safe_name(text):
        return re.sub(r"[^A-Za-z0-9_.-]", "-", text)


    def budget_suffix(max_gen_toks):
        """'' for the standard budget, else '32k' style (matches summarize.series_label)."""
        if max_gen_toks == MAX_GEN_TOKS:
            return ""
        return f"{max_gen_toks // 1024}k" if max_gen_toks % 1024 == 0 else str(max_gen_toks)


    def run_name(model_id, task, pilot, stamp, max_gen_toks=MAX_GEN_TOKS):
        suffix = budget_suffix(max_gen_toks)
        parts = [safe_name(model_id), task] + ([suffix] if suffix else []) + (["pilot"] if pilot else []) + [stamp]
        return "-".join(parts)


    def request_timeout(max_gen_toks):
        return max(REQUEST_TIMEOUT, int(max_gen_toks * SECONDS_PER_TOKEN))


    def context_problem(server, max_gen_toks, headroom=PROMPT_HEADROOM):
        """None if the server's per-slot context fits the budget (or is unknown), else why not."""
        n_ctx = ((server.get("props") or {}).get("n_ctx"))
        if isinstance(n_ctx, int) and n_ctx < (max_gen_toks or 0) + headroom:
            return (f"server per-slot context {n_ctx} can't hold max_gen_toks {max_gen_toks} "
                    f"plus ~{headroom} prompt tokens")
        return None


    def lm_eval_argv(base_url, model_id, tasks, concurrency, limit, run_dir, max_gen_toks=MAX_GEN_TOKS):
        argv = [
            "lm_eval", "run",
            "--model", "local-chat-completions",
            "--model_args",
            f"base_url={base_url}/v1/chat/completions,model={model_id},"
            f"num_concurrent={concurrency},tokenized_requests=False,timeout={request_timeout(max_gen_toks)}",
            "--tasks", ",".join(tasks),
            "--apply_chat_template", "--log_samples",
            "--gen_kwargs", f"max_gen_toks={max_gen_toks}",
        ]
        if limit:
            argv += ["--limit", str(limit)]
        argv += [
            "--use_cache", os.path.join(run_dir, "cache", "responses"),
            "--output_path", run_dir,
        ]
        return argv


    def _lm_eval_version():
        try:
            from importlib.metadata import version
            return version("lm_eval")
        except Exception:
            return None


    def _now_stamp():
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


    def wrapper_argv(harness, run_dir):
        return ["python", f"/opt/eval-runner/{harness}_run.py", run_dir]


    def build_record(server, task, pilot, limit, concurrency, note, stamp, results_root, max_gen_toks=MAX_GEN_TOKS):
        harness = HARNESS[task]
        if harness != "lm_eval":
            max_gen_toks = WRAPPER_MAX_GEN_TOKS[harness]
        if limit is None and pilot:
            limit = PILOT_LIMIT if harness == "lm_eval" else WRAPPER_PILOT_LIMITS[harness]
        name = run_name(server["model_id"], task, pilot, stamp,
                        max_gen_toks if harness == "lm_eval" else MAX_GEN_TOKS)
        run_dir = os.path.join(results_root, name)
        argv = (lm_eval_argv(server["base_url"], server["model_id"], TASKS[task], concurrency, limit, run_dir,
                             max_gen_toks)
                if harness == "lm_eval" else wrapper_argv(harness, run_dir))
        return {
            "run": name,
            "task": task,
            "harness": harness,
            "tasks": TASKS[task],
            "pilot": pilot,
            "limit": limit,
            "concurrency": concurrency,
            "max_gen_toks": max_gen_toks,
            "note": note,
            "created_utc": stamp,
            "lm_eval_version": _lm_eval_version(),
            "server": server,
            "fingerprint": fingerprint(server),
            # The command `exec` runs (named for lm_eval, which came first; for
            # the wrappers it is their own command line).
            "lm_eval_argv": argv,
        }, run_dir


    def load_record(run_dir):
        with open(os.path.join(run_dir, "run.json")) as fh:
            return json.load(fh)


    def cmd_start(args):
        server = snapshot_server(args.base_url, os.environ.get("OPENAI_API_KEY", ""))
        harness = HARNESS[args.task]
        problem = (context_problem(server, args.max_gen_toks) if harness == "lm_eval" else
                   context_problem(server, WRAPPER_MAX_GEN_TOKS[harness], WRAPPER_PROMPT_HEADROOM[harness]))
        if problem:
            print(f"runmeta: {problem}", file=sys.stderr)
            return 2
        record, run_dir = build_record(
            server, args.task, args.pilot, args.limit, args.concurrency, args.note,
            args.stamp or _now_stamp(), args.results_root, args.max_gen_toks,
        )
        os.makedirs(run_dir)  # fails loudly if the run already exists
        with open(os.path.join(run_dir, "run.json"), "w") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        print(record["run"])
        return 0


    def cmd_exec(args):
        argv = load_record(args.run_dir)["lm_eval_argv"]
        os.execvp(argv[0], argv)


    def cmd_field(args):
        """Print one top-level run.json field (eval-run uses it to pick the image)."""
        value = load_record(args.run_dir).get(args.key)
        print("" if value is None else value)
        return 0


    def cmd_check(args):
        record = load_record(args.run_dir)
        base_url = args.base_url or record["server"]["base_url"]
        now = snapshot_server(base_url, os.environ.get("OPENAI_API_KEY", ""))
        if fingerprint(now) == record["fingerprint"]:
            print(f"server unchanged since {record['run']} started")
            return 0
        print(f"server changed since {record['run']} started:")
        for line in server_changes(record["server"], now):
            print(f"  {line}")
        return EXIT_CHANGED


    def main(argv=None):
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        sub = parser.add_subparsers(dest="cmd", required=True)

        start = sub.add_parser("start")
        start.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL"))
        start.add_argument("--task", choices=sorted(TASKS), required=True)
        start.add_argument("--pilot", action="store_true")
        start.add_argument("--limit", type=int)
        start.add_argument("--concurrency", type=int, default=1)
        start.add_argument("--note", default="")
        start.add_argument("--max-gen-toks", type=int, default=MAX_GEN_TOKS)
        start.add_argument("--stamp")
        start.add_argument("--results-root", default="/results")

        run_exec = sub.add_parser("exec")
        run_exec.add_argument("run_dir")

        check = sub.add_parser("check")
        check.add_argument("run_dir")
        check.add_argument("--base-url")

        field = sub.add_parser("field")
        field.add_argument("run_dir")
        field.add_argument("key")

        args = parser.parse_args(argv)
        if args.cmd == "start":
            if not args.base_url:
                parser.error("--base-url or LLM_BASE_URL is required")
            if args.concurrency < 1:
                parser.error("--concurrency must be >= 1")
            if args.max_gen_toks < MAX_GEN_TOKS:
                parser.error(f"--max-gen-toks below {MAX_GEN_TOKS} truncates reasoning models (Bug 6)")
            if HARNESS[args.task] != "lm_eval" and args.max_gen_toks != MAX_GEN_TOKS:
                parser.error(f"--max-gen-toks only applies to gpqa/ifeval; {args.task} uses its historical budget")
            return cmd_start(args)
        if args.cmd == "exec":
            return cmd_exec(args)
        if args.cmd == "field":
            return cmd_field(args)
        return cmd_check(args)


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/runmeta.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/runmeta.py | cut -d' ' -f1"
    expect: "946fd0acdab10f009624925e44f1cb2f1619552e009f1fe79de358eb5b6d1ebe"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/runmeta.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-06e-selftest-checks

```yaml
id: eval-runner-06e-selftest-checks
title: Add the selftest request/flag assertions
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/selftest_checks.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Assertions run by selftest.sh after lm_eval has talked to mock_openai.py.

      requests  Every chat-completion request lm_eval sent carries the settings
                the eval battery depends on: max_tokens 8192 (the Bug 6
                regression guard), temperature 0 (greedy, as every historical
                result used), seed 1234, the served model id, and a non-empty
                chat message list ending in a user turn. Also checks the count.
      flags     summarize.py's empty-response flags add up to what the mock was
                told to produce, and run.json carries a fingerprint and props.
      wrapper   (--harness bfcl|agentbench|repobench) Every request the
                wrapper sent matches how its historical results were produced:
                BFCL -- tools present, temperature 0.001, no max_tokens;
                AgentBench -- temperature 0, max_tokens 3072; RepoBench --
                raw completions, temperature 0, max_tokens 128. Plus the
                served model id and the request count.
      publish   After publishing twice to mock_nextcloud.py: one table with every
                column, the expected rows (no duplicates from the second
                publish), every view, one share, the report files including
                leaderboard.xlsx, and the stale leaderboard.csv deleted.
    """

    import argparse
    import json
    import os
    import sys
    import urllib.request

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import publish  # noqa: E402
    import runmeta  # noqa: E402
    import summarize  # noqa: E402

    EXPECTED_TEMPERATURE = 0
    EXPECTED_SEED = 1234


    def request_errors(path, expected_count, model):
        with open(path) as fh:
            requests = [json.loads(line) for line in fh if line.strip()]
        errors = []
        if len(requests) != expected_count:
            errors.append(f"expected {expected_count} requests, mock saw {len(requests)}")
        for i, req in enumerate(requests, 1):
            if req.get("max_tokens") != runmeta.MAX_GEN_TOKS:
                errors.append(f"request {i}: max_tokens {req.get('max_tokens')!r}, want {runmeta.MAX_GEN_TOKS}")
            if req.get("temperature") != EXPECTED_TEMPERATURE:
                errors.append(f"request {i}: temperature {req.get('temperature')!r}, want {EXPECTED_TEMPERATURE}")
            if req.get("seed") != EXPECTED_SEED:
                errors.append(f"request {i}: seed {req.get('seed')!r}, want {EXPECTED_SEED}")
            if req.get("model") != model:
                errors.append(f"request {i}: model {req.get('model')!r}, want {model!r}")
            messages = req.get("messages")
            if not isinstance(messages, list) or not messages or messages[-1].get("role") != "user":
                errors.append(f"request {i}: messages must be a non-empty list ending with a user turn")
        return errors


    # harness -> {field: expected value}; MISSING means the field must be absent.
    MISSING = object()
    WRAPPER_REQUESTS = {
        "bfcl": {"temperature": 0.001, "max_tokens": MISSING},
        "agentbench": {"temperature": 0, "max_tokens": 3072},
        "repobench": {"temperature": 0, "max_tokens": 128},
    }


    def wrapper_request_errors(path, expected_count, model, harness):
        with open(path) as fh:
            requests = [json.loads(line) for line in fh if line.strip()]
        errors = []
        if len(requests) != expected_count:
            errors.append(f"expected {expected_count} requests, mock saw {len(requests)}")
        for i, req in enumerate(requests, 1):
            for field, want in WRAPPER_REQUESTS[harness].items():
                if want is MISSING and field in req:
                    errors.append(f"request {i}: {field} {req[field]!r} sent, historical runs sent none")
                elif want is not MISSING and req.get(field) != want:
                    errors.append(f"request {i}: {field} {req.get(field)!r}, want {want!r}")
            if req.get("model") != model:
                errors.append(f"request {i}: model {req.get('model')!r}, want {model!r}")
            if harness == "bfcl" and not req.get("tools"):
                errors.append(f"request {i}: no tools (BFCL runs in native function-calling mode)")
        return errors


    def flag_errors(run_dir, expected_empty):
        errors = []
        found = summarize.load(run_dir)
        total_empty = 0
        for task in summarize.LM_EVAL_TASKS:
            entry = found.get(task)
            if not entry or not entry["samples"]:
                errors.append(f"{task}: no results/samples file")
                continue
            total_empty += summarize.response_flags(entry["samples"], task)["empty"]
        if total_empty != expected_empty:
            errors.append(f"expected {expected_empty} empty responses across tasks, summarize counted {total_empty}")
        record = runmeta.load_record(run_dir)
        if not record.get("fingerprint") or not (record.get("server") or {}).get("props"):
            errors.append("run.json is missing the server fingerprint or props")
        return errors


    def publish_errors(state, expected_rows, run):
        errors = []
        if [t["title"] for t in state["tables"]] != [publish.TABLE_TITLE]:
            errors.append(f"expected exactly one '{publish.TABLE_TITLE}' table, got {state['tables']}")
        titles = [c["title"] for c in state["columns"]]
        if titles != [t for t, _ in publish.COLUMNS]:
            errors.append(f"columns {titles} don't match publish.COLUMNS")
        if len(state["rows"]) != expected_rows:
            errors.append(f"expected {expected_rows} rows, table has {len(state['rows'])}")
        if state["tables"] and len(state["tables"][0].get("columnSettings") or []) != len(publish.COLUMNS):
            errors.append("table column order (OCS v2 columnSettings) was not applied")
        if len(state["views"]) != len(publish.VIEWS) or len(state["shares"]) != 1:
            errors.append(f"expected {len(publish.VIEWS)} views and 1 share, got "
                          f"{len(state['views'])} and {len(state['shares'])}")
        for rel in ("leaderboard.md", "leaderboard.xlsx", "findings.md", f"runs/{run}/report.md",
                    f"runs/{run}/manifest.json"):
            if f"{publish.FOLDER}/{rel}" not in state["files"]:
                errors.append(f"missing published file {rel}")
        xlsx = state["files"].get(f"{publish.FOLDER}/leaderboard.xlsx", "")
        if xlsx and not (xlsx.startswith("<binary") and xlsx.endswith(" zip>")):
            errors.append(f"leaderboard.xlsx is not a zip container: {xlsx[:60]!r}")
        for rel in publish.STALE_FILES:
            if f"{publish.FOLDER}/{rel}" not in state.get("deleted", []):
                errors.append(f"stale file {rel} was not deleted")
        if any("samples_" in name for name in state["files"]):
            errors.append("a samples file was published (GPQA questions must not leave the CT)")
        return errors


    def main(argv=None):
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--requests")
        parser.add_argument("--expect-requests", type=int)
        parser.add_argument("--model")
        parser.add_argument("--run-dir")
        parser.add_argument("--expect-empty", type=int)
        parser.add_argument("--nextcloud-state", help="mock_nextcloud.py /_mock/state URL")
        parser.add_argument("--expect-rows", type=int)
        parser.add_argument("--published-run")
        parser.add_argument("--harness", choices=sorted(WRAPPER_REQUESTS))
        args = parser.parse_args(argv)

        errors = []
        if args.requests and args.harness:
            errors += wrapper_request_errors(args.requests, args.expect_requests, args.model, args.harness)
        elif args.requests:
            errors += request_errors(args.requests, args.expect_requests, args.model)
        if args.run_dir is not None:
            errors += flag_errors(args.run_dir, args.expect_empty)
        if args.nextcloud_state:
            with urllib.request.urlopen(args.nextcloud_state, timeout=10) as resp:
                errors += publish_errors(json.load(resp), args.expect_rows, args.published_run)
        for line in errors:
            print(f"FAIL: {line}", file=sys.stderr)
        if errors:
            return 1
        print("checks OK" + (f" ({args.expect_requests} requests)" if args.requests else " (publish)"))
        return 0


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/selftest_checks.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/selftest_checks.py | cut -d' ' -f1"
    expect: "fff110cedd8104a999a47a2b35ebd51feb476404772c8d8445dad317c0046a25"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/selftest_checks.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-06f-test-runmeta

```yaml
id: eval-runner-06f-test-runmeta
title: Add runmeta unit tests
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/test_runmeta.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Unit tests for runmeta.py. Run with:
    python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
    """

    import copy
    import json
    import os
    import tempfile
    import unittest
    from unittest import mock

    import runmeta

    PROPS = {
        "model_path": "/m/glm.gguf",
        "model_alias": "glm-5.3-flash",
        "build_info": "b1-abc",
        "total_slots": 4,
        "chat_template": "{{ x }}",
        "default_generation_settings": {
            "n_ctx": 131072,
            "params": {"temperature": 1.0, "top_p": 0.95, "min_p": 0.01, "n_predict": -1, "seed": 4294967295,
                       "unrelated": "ignored"},
        },
    }


    def fake_get(models_id="glm-5.3-flash", props=PROPS):
        def get_json(url, api_key):
            if url.endswith("/v1/models"):
                return {"data": [{"id": models_id}]}
            if props is None:
                raise OSError("no /props")
            return copy.deepcopy(props)
        return get_json


    class SnapshotTest(unittest.TestCase):
        def test_snapshot_records_props_subset(self):
            server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())
            self.assertEqual(server["model_id"], "glm-5.3-flash")
            self.assertEqual(server["props"]["model_path"], "/m/glm.gguf")
            self.assertEqual(server["props"]["n_ctx"], 131072)
            self.assertEqual(server["props"]["params"]["temperature"], 1.0)
            self.assertNotIn("unrelated", server["props"]["params"])
            self.assertEqual(len(server["props"]["chat_template_sha256"]), 64)

        def test_snapshot_without_props(self):
            server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(props=None))
            self.assertIsNone(server["props"])
            self.assertTrue(runmeta.fingerprint(server))

        def test_comma_in_model_id_rejected(self):
            with self.assertRaises(ValueError):
                runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(models_id="a,b"))


    class FingerprintTest(unittest.TestCase):
        def setUp(self):
            self.server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())

        def test_ignores_base_url_and_slots(self):
            other = copy.deepcopy(self.server)
            other["base_url"] = "http://192.168.1.18:8080"
            other["props"]["total_slots"] = 1
            self.assertEqual(runmeta.fingerprint(self.server), runmeta.fingerprint(other))
            self.assertEqual(runmeta.server_changes(self.server, other), [])

        def test_detects_model_template_and_sampling_changes(self):
            for path, value in (
                (("props", "model_path"), "/m/other.gguf"),
                (("props", "chat_template_sha256"), "0" * 64),
                (("props", "build_info"), "b2-def"),
            ):
                other = copy.deepcopy(self.server)
                other[path[0]][path[1]] = value
                self.assertNotEqual(runmeta.fingerprint(self.server), runmeta.fingerprint(other), path)
            other = copy.deepcopy(self.server)
            other["props"]["params"]["temperature"] = 0.6
            self.assertEqual(runmeta.server_changes(self.server, other), ["props.params.temperature: 1.0 -> 0.6"])


    class ArgvTest(unittest.TestCase):
        def test_argv_carries_battery_settings(self):
            argv = runmeta.lm_eval_argv("http://f:8080", "glm", ["ifeval"], 1, None, "/results/r")
            self.assertEqual(argv[:2], ["lm_eval", "run"])
            model_args = argv[argv.index("--model_args") + 1]
            self.assertIn("base_url=http://f:8080/v1/chat/completions", model_args)
            self.assertIn("model=glm", model_args)
            self.assertIn("num_concurrent=1", model_args)
            self.assertIn("timeout=3600", model_args)
            self.assertEqual(argv[argv.index("--gen_kwargs") + 1], "max_gen_toks=8192")
            self.assertIn("--apply_chat_template", argv)
            self.assertIn("--log_samples", argv)
            self.assertNotIn("--limit", argv)
            self.assertEqual(argv[argv.index("--use_cache") + 1], "/results/r/cache/responses")
            self.assertEqual(argv[argv.index("--output_path") + 1], "/results/r")

        def test_limit_added_when_set(self):
            argv = runmeta.lm_eval_argv("http://f:8080", "glm", ["ifeval"], 2, 40, "/r")
            self.assertEqual(argv[argv.index("--limit") + 1], "40")


    class RecordTest(unittest.TestCase):
        def setUp(self):
            self.server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())

        def test_pilot_defaults_limit_and_names_run(self):
            record, run_dir = runmeta.build_record(self.server, "gpqa", True, None, 1, "effort=high", "20261001T000000Z", "/results")
            self.assertEqual(record["run"], "glm-5.3-flash-gpqa-pilot-20261001T000000Z")
            self.assertEqual(run_dir, "/results/glm-5.3-flash-gpqa-pilot-20261001T000000Z")
            self.assertEqual(record["limit"], runmeta.PILOT_LIMIT)
            self.assertEqual(record["tasks"], ["gpqa_diamond_cot_zeroshot"])
            self.assertEqual(record["note"], "effort=high")
            self.assertEqual(record["fingerprint"], runmeta.fingerprint(self.server))

        def test_full_run_has_no_limit(self):
            record, _ = runmeta.build_record(self.server, "ifeval", False, None, 1, "", "S", "/results")
            self.assertIsNone(record["limit"])
            self.assertEqual(record["run"], "glm-5.3-flash-ifeval-S")

        def test_safe_name(self):
            self.assertEqual(runmeta.safe_name("org/model:q4 x"), "org-model-q4-x")


    class BudgetTest(unittest.TestCase):
        def setUp(self):
            self.server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())

        def test_32k_series_named_recorded_and_timed(self):
            record, _ = runmeta.build_record(self.server, "gpqa", False, None, 1, "", "S", "/results", 32768)
            self.assertEqual(record["run"], "glm-5.3-flash-gpqa-32k-S")
            self.assertEqual(record["max_gen_toks"], 32768)
            argv = record["lm_eval_argv"]
            self.assertEqual(argv[argv.index("--gen_kwargs") + 1], "max_gen_toks=32768")
            self.assertIn(f"timeout={runmeta.request_timeout(32768)}", argv[argv.index("--model_args") + 1])
            self.assertGreater(runmeta.request_timeout(32768), runmeta.REQUEST_TIMEOUT)

        def test_standard_budget_keeps_old_name_and_timeout(self):
            record, _ = runmeta.build_record(self.server, "gpqa", True, None, 1, "", "S", "/results")
            self.assertEqual(record["run"], "glm-5.3-flash-gpqa-pilot-S")
            self.assertEqual(record["max_gen_toks"], runmeta.MAX_GEN_TOKS)
            self.assertEqual(runmeta.request_timeout(runmeta.MAX_GEN_TOKS), runmeta.REQUEST_TIMEOUT)

        def test_context_too_small_refused(self):
            small = copy.deepcopy(PROPS)
            small["default_generation_settings"]["n_ctx"] = 32768
            server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(props=small))
            self.assertIsNotNone(runmeta.context_problem(server, 32768))
            self.assertIsNone(runmeta.context_problem(server, 8192))
            no_props = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(props=None))
            self.assertIsNone(runmeta.context_problem(no_props, 32768))
            with tempfile.TemporaryDirectory() as root:
                with mock.patch.object(runmeta, "_get_json", fake_get(props=small)), \
                        mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                    rc = runmeta.main(["start", "--base-url", "http://f:8080", "--task", "gpqa", "--stamp", "S",
                                       "--results-root", root, "--max-gen-toks", "32768"])
                self.assertEqual(rc, 2)
                self.assertEqual(os.listdir(root), [])

        def test_selftest_mock_passes_the_context_check(self):
            import mock_openai
            server = runmeta.snapshot_server("http://m", "k", get_json=fake_get(props=mock_openai.PROPS))
            self.assertIsNone(runmeta.context_problem(server, runmeta.MAX_GEN_TOKS))

        def test_budget_below_standard_rejected(self):
            with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                runmeta.main(["start", "--base-url", "http://f:8080", "--task", "gpqa", "--max-gen-toks", "4096"])


    class CommandTest(unittest.TestCase):
        def test_start_then_check_and_changed_exit_code(self):
            with tempfile.TemporaryDirectory() as root:
                with mock.patch.object(runmeta, "_get_json", fake_get()), \
                        mock.patch("sys.stdout"):
                    rc = runmeta.main(["start", "--base-url", "http://f:8080", "--task", "ifeval",
                                       "--stamp", "S", "--results-root", root])
                self.assertEqual(rc, 0)
                run_dir = os.path.join(root, "glm-5.3-flash-ifeval-S")
                with open(os.path.join(run_dir, "run.json")) as fh:
                    self.assertEqual(json.load(fh)["run"], "glm-5.3-flash-ifeval-S")

                with mock.patch.object(runmeta, "_get_json", fake_get()), mock.patch("sys.stdout"):
                    self.assertEqual(runmeta.main(["check", run_dir]), 0)

                changed = copy.deepcopy(PROPS)
                changed["model_path"] = "/m/other.gguf"
                with mock.patch.object(runmeta, "_get_json", fake_get(props=changed)), mock.patch("sys.stdout"):
                    self.assertEqual(runmeta.main(["check", run_dir]), runmeta.EXIT_CHANGED)

        def test_start_refuses_existing_run(self):
            with tempfile.TemporaryDirectory() as root:
                args = ["start", "--base-url", "http://f:8080", "--task", "gpqa", "--stamp", "S", "--results-root", root]
                with mock.patch.object(runmeta, "_get_json", fake_get()), mock.patch("sys.stdout"):
                    runmeta.main(args)
                    with self.assertRaises(FileExistsError):
                        runmeta.main(args)


    if __name__ == "__main__":
        unittest.main()

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/test_runmeta.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/test_runmeta.py | cut -d' ' -f1"
    expect: "2b479dd80e9197ac0ea82342b133aaebcb7f10d90d90d4979a8f2f7007f3cb7e"
    critical: true
```

### eval-runner-06g-test-summarize

```yaml
id: eval-runner-06g-test-summarize
title: Add summarize/selftest_checks unit tests
depends_on:
  - eval-runner-06c-summarize
  - eval-runner-06d-runmeta
  - eval-runner-06e-selftest-checks
  - eval-runner-06f-test-runmeta

change: |
  Create terraform/lxc/ansible/files/eval-runner/test_summarize.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Unit tests for summarize.py and selftest_checks.py. Run with:
    python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
    """

    import json
    import os
    import tempfile
    import unittest
    from unittest import mock

    import runmeta
    import selftest_checks
    import summarize

    STAMP = "2026-10-01T00-00-00.000000"


    COMPARABLE = {"limit": None, "gen_kwargs": {"max_gen_toks": 8192}, "model_args": {"model": "m:q4"}}


    def write_run(root, name, tasks, gpqa_rows=None, ifeval_rows=None, run_json=True, config=None):
        """Create a run dir shaped like lm_eval's output (<run>/<model>/results_*.json)."""
        run_dir = os.path.join(root, name)
        model_dir = os.path.join(run_dir, "model")
        os.makedirs(model_dir)
        results = {}
        n_samples = {}
        if "gpqa" in tasks:
            results["gpqa_diamond_cot_zeroshot"] = {"exact_match,flexible-extract": 0.5, "exact_match,strict-match": 0.25}
            # lm_eval counts questions, not rows (GPQA has one row per filter)
            n_samples["gpqa_diamond_cot_zeroshot"] = {"original": 198,
                                                      "effective": len({r["doc_id"] for r in gpqa_rows or []})}
        if "ifeval" in tasks:
            results["ifeval"] = {"prompt_level_strict_acc,none": 0.9, "prompt_level_loose_acc,none": 0.95}
            n_samples["ifeval"] = {"original": 541, "effective": len(ifeval_rows or [])}
        with open(os.path.join(model_dir, f"results_{STAMP}.json"), "w") as fh:
            json.dump({"results": results, "n-samples": n_samples, "config": config or COMPARABLE}, fh)
        for task, rows in (("gpqa_diamond_cot_zeroshot", gpqa_rows), ("ifeval", ifeval_rows)):
            if rows is not None:
                with open(os.path.join(model_dir, f"samples_{task}_{STAMP}.jsonl"), "w") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
        if run_json:
            with open(os.path.join(run_dir, "run.json"), "w") as fh:
                json.dump({"run": name, "fingerprint": "f", "server": {"props": {"model_path": "/m"}}}, fh)
        return run_dir


    def gpqa_rows(answers):
        """answers: list of raw response strings; each doc gets strict + flexible rows."""
        rows = []
        for doc_id, raw in enumerate(answers):
            parsed = "[invalid]" if "(" not in raw else "(A)"
            for filt in ("strict-match", "flexible-extract"):
                rows.append({"doc_id": doc_id, "filter": filt, "resps": [[raw]], "filtered_resps": [parsed]})
        return rows


    def ifeval_rows(answers):
        return [{"doc_id": i, "filter": "none", "resps": [[raw]], "filtered_resps": [raw]} for i, raw in enumerate(answers)]


    class FlagsTest(unittest.TestCase):
        def test_counts_per_question_not_per_filter_row(self):
            with tempfile.TemporaryDirectory() as root:
                run_dir = write_run(root, "r", ["gpqa"], gpqa_rows=gpqa_rows(["The answer is (A)", "", "no letter here"]))
                entry = summarize.load(run_dir)["gpqa_diamond_cot_zeroshot"]
                flags = summarize.response_flags(entry["samples"], "gpqa_diamond_cot_zeroshot")
                self.assertEqual(flags, {"questions": 3, "empty": 1, "unparsed": 2})

        def test_ifeval_has_no_unparsed(self):
            with tempfile.TemporaryDirectory() as root:
                run_dir = write_run(root, "r", ["ifeval"], ifeval_rows=ifeval_rows(["ok", "   ", "fine"]))
                entry = summarize.load(run_dir)["ifeval"]
                self.assertEqual(summarize.response_flags(entry["samples"], "ifeval"),
                                 {"questions": 3, "empty": 1, "unparsed": None})


    class DescribeTest(unittest.TestCase):
        def test_line_has_scores_and_flags(self):
            with tempfile.TemporaryDirectory() as root:
                run_dir = write_run(root, "glm-both", ["gpqa", "ifeval"],
                                    gpqa_rows=gpqa_rows(["(A)", ""]), ifeval_rows=ifeval_rows(["ok"]))
                line, ok = summarize.describe(run_dir, check=True)
                self.assertTrue(ok)
                self.assertIn("GPQA flex 50.00%", line)
                self.assertIn("IFEval p-loose 95.00%", line)
                self.assertIn("[empty 1, unparsed 1 <- inspect samples]", line)
                self.assertIn("[empty 0]", line)

        def test_check_fails_when_task_missing(self):
            with tempfile.TemporaryDirectory() as root:
                run_dir = write_run(root, "gpqa-only", ["gpqa"], gpqa_rows=gpqa_rows(["(A)"]))
                self.assertFalse(summarize.describe(run_dir, check=True)[1])
                self.assertTrue(summarize.describe(run_dir, check=False)[1])

        def test_empty_dir_reports_no_results(self):
            with tempfile.TemporaryDirectory() as root:
                os.makedirs(os.path.join(root, "pending"))
                line, ok = summarize.describe(os.path.join(root, "pending"), check=False)
                self.assertIn("no results yet", line)
                self.assertFalse(ok)

        def test_main_skips_underscore_dirs(self):
            with tempfile.TemporaryDirectory() as root:
                write_run(root, "_selftest", ["ifeval"], ifeval_rows=ifeval_rows(["x"]))
                write_run(root, "real", ["ifeval"], ifeval_rows=ifeval_rows(["x"]))
                with mock.patch.object(summarize, "RESULTS_ROOT", root), mock.patch("builtins.print") as printed:
                    summarize.main([])
                lines = [call.args[0] for call in printed.call_args_list]
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith("real:"))


    class ComparabilityTest(unittest.TestCase):
        def test_full_run_with_token_cap_is_comparable(self):
            self.assertIsNone(summarize.exclusion_reason({"config": COMPARABLE}))
            as_string = {"limit": None, "gen_kwargs": "max_gen_toks=8192,temperature=0"}
            self.assertIsNone(summarize.exclusion_reason({"config": as_string}))

        def test_pilot_and_bug6_excluded(self):
            self.assertEqual(summarize.exclusion_reason({"config": {"limit": 40.0, "gen_kwargs": {"max_gen_toks": 8192}}}),
                             "pilot (limit 40)")
            self.assertIn("Bug 6", summarize.exclusion_reason({"config": {"limit": None, "gen_kwargs": {}}}))
            self.assertIn("Bug 6", summarize.exclusion_reason({"config": {"limit": None, "gen_kwargs": {"max_gen_toks": 256}}}))

        def test_larger_budget_is_its_own_series(self):
            big = {"limit": None, "gen_kwargs": {"max_gen_toks": 32768}}
            self.assertEqual(summarize.exclusion_reason({"config": big}), "token budget 32768 (separate 32k series)")
            self.assertEqual(summarize.series({"config": big}), "32k")
            self.assertEqual(summarize.series({"config": COMPARABLE}), "8k")
            self.assertIsNone(summarize.series({"config": {"limit": 40, "gen_kwargs": {"max_gen_toks": 32768}}}))
            self.assertIsNone(summarize.series({"config": {"limit": None, "gen_kwargs": {"max_gen_toks": 256}}}))
            self.assertIsNone(summarize.series({"config": {"limit": None, "gen_kwargs": {}}}))

        def test_model_name_dict_or_string(self):
            self.assertEqual(summarize.model_name({"config": {"model_args": {"model": "x"}}}), "x")
            self.assertEqual(summarize.model_name({"config": {"model_args": "base_url=u,model=y,num_concurrent=1"}}), "y")

        def test_historical_section_filters_and_explains(self):
            with tempfile.TemporaryDirectory() as root:
                hist = os.path.join(root, summarize.HISTORICAL_DIR)
                os.makedirs(hist)
                write_run(hist, "good", ["gpqa", "ifeval"], gpqa_rows=gpqa_rows(["(A)"]), ifeval_rows=ifeval_rows(["ok"]))
                write_run(hist, "bug6", ["ifeval"], ifeval_rows=ifeval_rows(["ok"]),
                          config={"limit": None, "gen_kwargs": {}})
                lines = summarize.historical_lines(root)
            text = "\n".join(lines)
            self.assertIn("  good: GPQA flex 50.00%", text)
            self.assertIn("(m:q4)", text)
            self.assertNotIn("  bug6: ", text)
            self.assertIn("excluded:\n  bug6 ifeval: no max_gen_toks=8192", text)

        def test_no_historical_dir_adds_nothing(self):
            with tempfile.TemporaryDirectory() as root:
                self.assertEqual(summarize.historical_lines(root), [])


    class SelftestChecksTest(unittest.TestCase):
        def _log(self, root, requests):
            path = os.path.join(root, "req.jsonl")
            with open(path, "w") as fh:
                for req in requests:
                    fh.write(json.dumps(req) + "\n")
            return path

        def good(self):
            return {"model": "m", "max_tokens": runmeta.MAX_GEN_TOKS, "temperature": 0, "seed": 1234,
                    "messages": [{"role": "user", "content": "q"}]}

        def test_good_requests_pass(self):
            with tempfile.TemporaryDirectory() as root:
                self.assertEqual(selftest_checks.request_errors(self._log(root, [self.good()] * 2), 2, "m"), [])

        def test_bug6_truncation_caught(self):
            bad = self.good()
            bad["max_tokens"] = 256
            with tempfile.TemporaryDirectory() as root:
                errors = selftest_checks.request_errors(self._log(root, [bad]), 1, "m")
            self.assertTrue(any("max_tokens 256" in e for e in errors))

        def test_count_temperature_and_messages_checked(self):
            bad = self.good()
            bad["temperature"] = 1.0
            bad["messages"] = []
            with tempfile.TemporaryDirectory() as root:
                errors = selftest_checks.request_errors(self._log(root, [bad]), 3, "m")
            self.assertEqual(len(errors), 3)

        def test_flag_errors(self):
            with tempfile.TemporaryDirectory() as root:
                run_dir = write_run(root, "r", ["gpqa", "ifeval"],
                                    gpqa_rows=gpqa_rows(["", "(A)"]), ifeval_rows=ifeval_rows(["", "ok"]))
                self.assertEqual(selftest_checks.flag_errors(run_dir, 2), [])
                self.assertEqual(len(selftest_checks.flag_errors(run_dir, 3)), 1)


    if __name__ == "__main__":
        unittest.main()

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/test_summarize.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/test_summarize.py | cut -d' ' -f1"
    expect: "c48d2b920cd3ccbfcee64b96bf298173ea22ed7c7d91b1525121a55507b17297"
    critical: true
  - id: unit-tests
    cmd: "python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner/ -p 'test_*.py' 2>&1 | tail -1"
    expect: "OK, or OK (skipped=N) where openpyxl/rapidfuzz are not installed"
    critical: true
```

### eval-runner-06h-publish

```yaml
id: eval-runner-06h-publish
title: Add the Nextcloud publisher
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/publish.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Publish eval results to Nextcloud.

    What gets published (all under the service account, folder shared to the
    operator by the deploy):

      Reports/eval-runner/
        leaderboard.xlsx    the spreadsheet: one ranked sheet per task and
                            token-budget series, plus every result on one
                            filterable sheet (opens in Nextcloud Office)
        leaderboard.md      the ranked lists as plain text
        findings.md         curated analysis (from the repo)
        runs/<run>/report.md, manifest.json            eval-runner runs
        historical/<source>/report.md, manifest.json   imported framework runs

    and the Nextcloud Tables table "Model evaluations": one row per
    (run, task, results file), upserted by its Key column, with saved views
    for comparable GPQA / IFEval results.

    The report/manifest layout follows docs/reporting-platform/CONVENTION.md.
    samples_*.jsonl files are never uploaded: they contain GPQA questions,
    whose licence forbids reposting them.

    Environment (from /etc/eval-runner/eval-runner.env):
      NEXTCLOUD_EVAL_REPORTS_URL           e.g. https://nextcloud.lab.gibbsgreatly.xyz
      NEXTCLOUD_EVAL_REPORTS_USER          service account
      NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD  its app password
      NEXTCLOUD_EVAL_TABLE_SHARE_WITH      user to share the table with (optional)

    Usage:
      publish.py                    publish everything
      publish.py --dry-run DIR      render everything into DIR, no network
    """

    import argparse
    import base64
    import datetime
    import glob
    import io
    import json
    import os
    import sys
    import urllib.error
    import urllib.parse
    import urllib.request

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import summarize  # noqa: E402

    try:  # only needed to render leaderboard.xlsx; in the image, see the Dockerfile
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:  # pragma: no cover - unit tests skip the xlsx checks
        openpyxl = None

    RESULTS_ROOT = "/results"
    FINDINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "findings.md")
    FOLDER = "Reports/eval-runner"
    TABLE_TITLE = "Model evaluations"
    TABLE_EMOJI = "📊"
    TABLES_API = "/index.php/apps/tables/api/1"
    TABLES_OCS_API = "/ocs/v2.php/apps/tables/api/2"
    # Files earlier versions published that are now gone; deleted on publish.
    STALE_FILES = ("leaderboard.csv",)

    # task -> (label, primary metric name, alternative metric name or None).
    # Order is the leaderboard's section and sheet order.
    TASK_LABELS = {
        "gpqa_diamond_cot_zeroshot": ("GPQA diamond", "flexible-extract", "strict-match"),
        "ifeval": ("IFEval", "prompt-level strict", "prompt-level loose"),
        "bfcl_simple": ("BFCL simple", "accuracy", None),
        "agentbench_os_std": ("AgentBench os-std", "success rate", None),
        "repobench_python": ("RepoBench (rebuilt)", "exact match", "edit similarity"),
    }
    TASK_BY_LABEL = {label: task for task, (label, _, _) in TASK_LABELS.items()}

    # (title, column spec). Order is the table's column order. "Key" is the
    # upsert identity and must stay first and unchanged.
    COLUMNS = [
        ("Key", {"type": "text", "subtype": "line"}),
        ("Model", {"type": "text", "subtype": "line"}),
        ("Task", {"type": "text", "subtype": "line"}),
        ("Score %", {"type": "number", "numberDecimals": 2, "numberSuffix": "%"}),
        ("Alt score %", {"type": "number", "numberDecimals": 2, "numberSuffix": "%"}),
        ("Metrics", {"type": "text", "subtype": "line"}),
        ("Questions", {"type": "number", "numberDecimals": 0}),
        ("Empty answers", {"type": "number", "numberDecimals": 0}),
        ("Empty %", {"type": "number", "numberDecimals": 1, "numberSuffix": "%"}),
        ("Unparsed", {"type": "number", "numberDecimals": 0}),
        ("Token budget", {"type": "number", "numberDecimals": 0}),
        ("Series", {"type": "text", "subtype": "line"}),
        ("Comparable", {"type": "text", "subtype": "line"}),
        ("Why not comparable", {"type": "text", "subtype": "line"}),
        ("Model file / tag", {"type": "text", "subtype": "line"}),
        ("Runtime", {"type": "text", "subtype": "line"}),
        ("Note", {"type": "text", "subtype": "line"}),
        ("Source", {"type": "text", "subtype": "line"}),
        ("Run", {"type": "text", "subtype": "line"}),
        ("Date", {"type": "text", "subtype": "line"}),
        ("Report", {"type": "text", "subtype": "line"}),
    ]

    VIEWS = [
        # (title, emoji, task label, {column: required value})
        ("Comparable: GPQA", "🧠", "GPQA diamond", {"Comparable": "yes"}),
        ("Comparable: IFEval", "📋", "IFEval", {"Comparable": "yes"}),
        ("Comparable: BFCL", "🔧", "BFCL simple", {"Comparable": "yes"}),
        ("Comparable: AgentBench", "🤖", "AgentBench os-std", {"Comparable": "yes"}),
        ("RepoBench (rebuilt)", "💻", "RepoBench (rebuilt)", {"Comparable": "yes"}),
        ("32k budget: GPQA", "⏳", "GPQA diamond", {"Series": "32k"}),
        ("32k budget: IFEval", "⏳", "IFEval", {"Series": "32k"}),
    ]



    # ---------------------------------------------------------------- collect

    def _base_url(data):
        model_args = data.get("config", {}).get("model_args")
        if isinstance(model_args, dict):
            return model_args.get("base_url", "")
        pairs = dict(p.split("=", 1) for p in str(model_args or "").split(",") if "=" in p)
        return pairs.get("base_url", "")


    def _date(data, fallback):
        stamp = data.get("date")
        if isinstance(stamp, (int, float)):
            return datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).strftime("%Y-%m-%d")
        return fallback


    def _runtime(data, record):
        wrapper = data.get("config", {}).get("eval_runner") or {}
        if wrapper.get("runtime"):
            return wrapper["runtime"]
        if record and (record.get("server") or {}).get("props"):
            return f"llama.cpp {record['server']['props'].get('build_info') or ''}".strip()
        return "Ollama" if ":11434" in _base_url(data) else "OpenAI-compatible server"


    def _model_file(model, record):
        props = (record or {}).get("server", {}).get("props") or {}
        if props.get("model_path"):
            return os.path.basename(props["model_path"])
        return model or ""


    def _stamp_date(stamp):
        """20261001T030837Z -> 2026-10-01"""
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 and stamp[:8].isdigit() else ""


    def _row(source, run, task, data, metrics, samples, record, stamp):
        label, primary_name, alt_name = TASK_LABELS[task]
        keys = [key for _, key in summarize.HEADLINE[task]]
        primary_key, alt_key = keys[0], (keys[1] if len(keys) > 1 else None)
        n = data.get("n-samples", {}).get(task, {}).get("effective")
        flags = summarize.task_flags(task, metrics, samples) or {"empty": None, "unparsed": None}
        wrapper = data.get("config", {}).get("eval_runner") or {}
        reason = summarize.exclusion_reason(data)
        model = (record or {}).get("server", {}).get("model_id") or summarize.model_name(data) or run

        def pct(value):
            return round(value * 100, 2) if isinstance(value, (int, float)) else None

        empty = flags["empty"]
        return {
            "Key": f"{source}/{run}/{task}" + (f"/{stamp}" if source == "historical" else ""),
            "Model": model,
            "Task": label,
            "Score %": pct(metrics.get(primary_key)),
            "Alt score %": pct(metrics.get(alt_key)),
            "Metrics": f"{primary_name} / {alt_name}" if alt_name else primary_name,
            "Questions": n,
            "Empty answers": empty,
            "Empty %": round(100 * empty / n, 1) if empty is not None and n else None,
            "Unparsed": flags["unparsed"],
            "Token budget": summarize._max_gen_toks(data.get("config", {}).get("gen_kwargs")),
            "Series": summarize.series(data) or "",
            "Comparable": "no" if reason else "yes",
            "Why not comparable": reason or "",
            "Model file / tag": _model_file(model, record),
            "Runtime": _runtime(data, record),
            "Note": (record or {}).get("note") or wrapper.get("note") or "",
            "Source": "eval-runner" if source == "runs" else f"historical ({wrapper.get('origin') or 'framework'})",
            "Run": run,
            "Date": _date(data, _stamp_date((record or {}).get("created_utc", ""))),
            "Report": f"{FOLDER}/{source}/{run}/report.md",
        }


    def _results_files(run_dir):
        return sorted(glob.glob(os.path.join(run_dir, "**", "results_*.json"), recursive=True))


    def collect_run(run_dir, source):
        """Rows for one run directory. eval-runner runs: newest results file per
        task (a resume supersedes earlier files). Historical: every results file,
        so excluded pilots/Bug 6 runs stay visible with their reason."""
        run = os.path.basename(os.path.normpath(run_dir))
        record_path = os.path.join(run_dir, "run.json")
        record = None
        if os.path.exists(record_path):
            with open(record_path) as fh:
                record = json.load(fh)
        rows = {}
        for path in _results_files(run_dir):
            with open(path) as fh:
                data = json.load(fh)
            stamp = summarize._results_stamp(path)
            for task, metrics in data.get("results", {}).items():
                if task not in summarize.HEADLINE:
                    continue
                samples = os.path.join(os.path.dirname(path), f"samples_{task}_{stamp}.jsonl")
                row = _row(source, run, task, data, metrics,
                           samples if os.path.exists(samples) else None, record, stamp)
                rows[row["Key"]] = row
        return record, list(rows.values())


    def collect(results_root):
        """[(source, run_dir, record, rows)] for every eval-runner and historical run."""
        out = []
        for run_dir in sorted(glob.glob(os.path.join(results_root, "*"))):
            if os.path.isdir(run_dir) and not os.path.basename(run_dir).startswith("_"):
                record, rows = collect_run(run_dir, "runs")
                out.append(("runs", run_dir, record, rows))
        hist = os.path.join(results_root, summarize.HISTORICAL_DIR)
        for run_dir in sorted(glob.glob(os.path.join(hist, "*"))):
            if os.path.isdir(run_dir):
                record, rows = collect_run(run_dir, "historical")
                out.append(("historical", run_dir, record, rows))
        return out


    # ----------------------------------------------------------------- render

    def _fmt(value, suffix="", decimals=2):
        if value is None or value == "":
            return "–"
        if isinstance(value, float):
            return f"{value:.{decimals}f}{suffix}"
        return f"{value}{suffix}"


    CAVEATS = """\
    - **Greedy decoding.** Both task configs pin `temperature: 0`, as every
      historical result did.
    - **Token budget.** `max_gen_toks` is 8192 unless the table says
      otherwise. An *empty answer* means the model produced no answer
      content, usually because its reasoning used up the budget. A score with
      many empty answers mostly measures finishing inside the budget. Read
      `findings.md` before comparing reasoning models.
    - **Comparable** means a full run (no `--limit`) at the 8192 budget.
      Pilots and runs without the cap (the Bug 6 era) are listed but not
      ranked.
    - **Series.** Full runs at a larger budget (e.g. 32k) are ranked in their
      own series, never against the 8k one: more budget lets reasoning models
      finish answers they would otherwise lose.
    - **BFCL** is v3 "simple" (400 cases, bfcl-eval 2025.8.6.2) and
      **AgentBench** is os-std on a seed-42 sample of 100 episodes, both as
      every historical number. An AgentBench run over all 800 episodes is
      its own series.
    - **RepoBench (rebuilt)** is a new series: the scripts behind the
      historical RepoBench numbers are lost, so those aren't ranked with it.
    - Per-question samples stay on the eval-runner CT, not in Nextcloud:
      GPQA's licence forbids reposting its questions.
    """

    TASK_ORDER = tuple(label for label, _, _ in TASK_LABELS.values())


    def standard_series(label):
        return summarize.STANDARD_SERIES[TASK_BY_LABEL[label]]


    def series_order(all_rows, label):
        """Series present for one task label: its standard series first (even
        with no rows yet), then the others by token budget."""
        standard = standard_series(label)
        found = {r["Series"]: r["Token budget"] or 0 for r in all_rows if r["Task"] == label and r["Series"]}
        found.setdefault(standard, 0)
        return sorted(found, key=lambda name: (name != standard, found[name], name))


    def series_heading(label, series):
        standard = standard_series(label)
        if series == standard:
            return "comparable runs"
        kind = "token budget series" if TASK_BY_LABEL[label] in summarize.LM_EVAL_TASKS else "series"
        return f"{series} {kind}, not comparable with {standard}"


    def ranked(all_rows, label, series):
        return sorted((r for r in all_rows if r["Task"] == label and r["Series"] == series),
                      key=lambda r: -(r["Score %"] or 0))


    def metric_names(label):
        """(primary, alternative or None) metric names for a task label."""
        _, primary, alt = TASK_LABELS[TASK_BY_LABEL[label]]
        return primary, alt


    def render_report(source, run_dir, record, rows):
        run = os.path.basename(os.path.normpath(run_dir))
        lines = [f"# {run}", ""]
        if rows:
            first = rows[0]
            lines += [
                f"- **Model:** {first['Model']} (`{first['Model file / tag']}`)",
                f"- **Runtime:** {first['Runtime']}",
                f"- **Source:** {first['Source']}",
            ]
        if record:
            props = (record.get("server") or {}).get("props") or {}
            params = props.get("params") or {}
            lines += [
                f"- **Started:** {record.get('created_utc', '')}",
                f"- **Note:** {record.get('note') or '–'}",
                f"- **Server:** n_ctx {props.get('n_ctx', '–')}, server-default sampling "
                f"temperature {params.get('temperature', '–')} / top_p {params.get('top_p', '–')} "
                "(requests override temperature to 0)",
                f"- **Fingerprint:** `{record.get('fingerprint', '')[:16]}`",
                f"- **lm_eval:** {record.get('lm_eval_version') or '–'}, "
                f"limit {record.get('limit') or 'none'}, concurrency {record.get('concurrency')}",
            ]
        lines += ["", "## Results", "",
                  "| Task | Score | Alt score | Metrics | Questions | Empty answers | Unparsed | Budget | Comparable | Date |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            comparable = r["Comparable"] + (f" ({r['Why not comparable']})" if r["Why not comparable"] else "")
            lines.append(
                f"| {r['Task']} | {_fmt(r['Score %'], '%')} | {_fmt(r['Alt score %'], '%')} | {r['Metrics']} | "
                f"{_fmt(r['Questions'])} | {_fmt(r['Empty answers'])} ({_fmt(r['Empty %'], '%', 1)}) | "
                f"{_fmt(r['Unparsed'])} | {_fmt(r['Token budget'])} | {comparable} | {r['Date']} |"
            )
        if not rows:
            lines.append("| – | no results yet | | | | | | | | |")
        lines += ["", "## Caveats", "", CAVEATS]
        return "\n".join(lines)


    def render_manifest(source, run_dir, record, rows):
        run = os.path.basename(os.path.normpath(run_dir))
        dates = sorted(r["Date"] for r in rows if r["Date"])
        scores = ", ".join(f"{r['Task']} {_fmt(r['Score %'], '%')}" for r in rows) or "no results yet"
        return {
            "project": "eval-runner",
            "run_id": run,
            "started_at": (record or {}).get("created_utc") or (dates[0] if dates else ""),
            "finished_at": dates[-1] if dates else "",
            "summary": f"{rows[0]['Model'] if rows else run}: {scores}",
            "source": source,
            "rows": rows,
        }


    def render_leaderboard(all_rows, generated):
        lines = ["# Model evaluations: leaderboard", "",
                 f"Generated {generated} by `eval-run publish`. The full detail is in "
                 f"`leaderboard.xlsx` and the Nextcloud Tables table **{TABLE_TITLE}**. "
                 "Analysis: `findings.md`.", ""]
        for label in TASK_ORDER:
            for series in series_order(all_rows, label):
                rows = ranked(all_rows, label, series)
                main, alt = metric_names(label)
                lines += [f"## {label}: {series_heading(label, series)}", "", f"Ranked by {main}.", "",
                          f"| # | Model | Score | {alt or '–'} | Empty answers | Date |",
                          "|---|---|---|---|---|---|"]
                for i, r in enumerate(rows, 1):
                    lines.append(
                        f"| {i} | {r['Model']} | {_fmt(r['Score %'], '%')} | {_fmt(r['Alt score %'], '%')} | "
                        f"{_fmt(r['Empty answers'])}/{_fmt(r['Questions'])} | {r['Date']} |"
                    )
                if not rows:
                    lines.append("| – | none yet | | | | |")
                lines.append("")
        excluded = [r for r in all_rows if not r["Series"]]
        if excluded:
            lines += ["## Not comparable (listed, not ranked)", "",
                      "| Model | Task | Score | Why |", "|---|---|---|---|"]
            for r in sorted(excluded, key=lambda r: (r["Model"], r["Task"], r["Run"])):
                lines.append(f"| {r['Model']} | {r['Task']} | {_fmt(r['Score %'], '%')} | {r['Why not comparable']} |")
            lines.append("")
        lines += ["## Caveats", "", CAVEATS]
        return "\n".join(lines)


    # Number formats for leaderboard.xlsx, by column title.
    XLSX_FORMATS = {"Score %": '0.00"%"', "Alt score %": '0.00"%"', "Empty %": '0.0"%"'}
    XLSX_HEADER_FILL = "DDE4EE"


    def _xlsx_sheet(wb, title, headers, rows, freeze):
        """One sheet: bold shaded header, frozen panes, autofilter, number
        formats and column widths sized to the content."""
        ws = wb.create_sheet(title)
        ws.append(headers)
        for row in rows:
            ws.append(row)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor=XLSX_HEADER_FILL)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        for idx, header in enumerate(headers, 1):
            letter = get_column_letter(idx)
            fmt = XLSX_FORMATS.get(header)
            if fmt:
                for cell in ws[letter][1:]:
                    cell.number_format = fmt
            longest = max([len(header)] + [len(str(v)) for v in ws[letter][1:] for v in [v.value] if v is not None])
            ws.column_dimensions[letter].width = min(max(longest + 2, 8), 60)
        ws.freeze_panes = freeze
        ws.auto_filter.ref = ws.dimensions
        return ws


    def render_xlsx(all_rows, generated):
        """leaderboard.xlsx: ranked sheets (task x series), All results, Notes."""
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        wb.properties.creator = "eval-runner"
        for label in TASK_ORDER:
            for series in series_order(all_rows, label):
                rows = ranked(all_rows, label, series)
                if not rows:
                    continue
                main, alt = metric_names(label)
                headers = ["Rank", "Model", f"Score % ({main})", f"{alt or 'Alt score'} %", "Empty answers", "Questions",
                           "Empty %", "Unparsed", "Runtime", "Model file / tag", "Note", "Date", "Source", "Run"]
                body = [[i, r["Model"], r["Score %"], r["Alt score %"], r["Empty answers"], r["Questions"],
                         r["Empty %"], r["Unparsed"], r["Runtime"], r["Model file / tag"], r["Note"],
                         r["Date"], r["Source"], r["Run"]] for i, r in enumerate(rows, 1)]
                ws = _xlsx_sheet(wb, f"{label.split()[0]} ({series})", headers, body, "C2")
                for col in "CD":
                    for cell in ws[col][1:]:
                        cell.number_format = XLSX_FORMATS["Score %"]
                for cell in ws["G"][1:]:
                    cell.number_format = XLSX_FORMATS["Empty %"]
        titles = [t for t, _ in COLUMNS if t != "Key"]
        everything = sorted(all_rows, key=lambda r: (r["Task"], r["Series"] or "~", -(r["Score %"] or 0)))
        _xlsx_sheet(wb, "All results", titles, [[r.get(t) for t in titles] for r in everything], "C2")
        notes = wb.create_sheet("Notes")
        notes.append([f"Generated {generated} by eval-run publish. Same data as the Nextcloud Tables "
                      f"table '{TABLE_TITLE}'. Analysis: findings.md."])
        notes.append([])
        for para in CAVEATS.replace("\n  ", " ").splitlines():
            notes.append([para.replace("**", "").replace("`", "").lstrip("- ")])
        notes.column_dimensions["A"].width = 120
        for row in notes.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


    def build_files(collected, findings_text, generated):
        """{relative path under FOLDER: bytes}"""
        files = {}
        all_rows = []
        for source, run_dir, record, rows in collected:
            run = os.path.basename(os.path.normpath(run_dir))
            files[f"{source}/{run}/report.md"] = render_report(source, run_dir, record, rows).encode()
            files[f"{source}/{run}/manifest.json"] = (
                json.dumps(render_manifest(source, run_dir, record, rows), indent=2) + "\n").encode()
            all_rows += rows
        files["leaderboard.md"] = render_leaderboard(all_rows, generated).encode()
        if openpyxl is not None:  # always installed in the image; selftest checks the file is there
            files["leaderboard.xlsx"] = render_xlsx(all_rows, generated)
        if findings_text is not None:
            files["findings.md"] = findings_text.encode()
        return files, all_rows


    # ------------------------------------------------------------------ client

    class NextcloudError(RuntimeError):
        pass


    class Nextcloud:
        def __init__(self, base_url, user, password, opener=None):
            self.base = base_url.rstrip("/")
            self.user = user
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            self.auth = f"Basic {token}"
            self.opener = opener or urllib.request.urlopen

        def request(self, method, path, body=None, raw=None, ok=(200, 201, 204)):
            headers = {"Authorization": self.auth, "OCS-APIRequest": "true", "Accept": "application/json"}
            data = raw
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
            try:
                with self.opener(req, timeout=60) as resp:
                    payload = resp.read()
                    status = resp.status
            except urllib.error.HTTPError as err:
                status, payload = err.code, err.read()
            except (urllib.error.URLError, OSError) as err:
                raise NextcloudError(f"{method} {path} -> {type(err).__name__}: {err}") from err
            if status not in ok:
                raise NextcloudError(f"{method} {path} -> HTTP {status}: {payload[:300]!r}")
            if payload and payload.lstrip()[:1] in (b"{", b"["):
                return json.loads(payload)
            return None

        # WebDAV
        def _dav(self, rel):
            quoted = "/".join(urllib.parse.quote(part) for part in rel.split("/"))
            return f"/remote.php/dav/files/{urllib.parse.quote(self.user)}/{quoted}"

        def ensure_folder(self, rel):
            parts = rel.strip("/").split("/")
            for i in range(1, len(parts) + 1):
                # 405 = already exists
                self.request("MKCOL", self._dav("/".join(parts[:i])), ok=(201, 405))

        def put_file(self, rel, content):
            self.request("PUT", self._dav(rel), raw=content, ok=(201, 204))

        def delete_file(self, rel):
            # 404 = already gone
            self.request("DELETE", self._dav(rel), ok=(204, 404))

        # Tables
        def tables(self, method, path, body=None):
            return self.request(method, TABLES_API + path, body=body)


    def ensure_table(nc):
        for table in nc.tables("GET", "/tables") or []:
            if table.get("title") == TABLE_TITLE:
                return table["id"]
        return nc.tables("POST", "/tables", {"title": TABLE_TITLE, "emoji": TABLE_EMOJI})["id"]


    def ensure_columns(nc, table_id):
        """{title: column id}, creating any missing columns in COLUMNS order."""
        existing = {c["title"]: c["id"] for c in nc.tables("GET", f"/tables/{table_id}/columns") or []}
        for title, spec in COLUMNS:
            if title not in existing:
                created = nc.tables("POST", f"/tables/{table_id}/columns",
                                    {"title": title, "mandatory": False, **spec})
                existing[title] = created["id"]
        return existing


    def _all_rows(nc, table_id, page=500):
        rows, offset = [], 0
        while True:
            batch = nc.tables("GET", f"/tables/{table_id}/rows?limit={page}&offset={offset}") or []
            rows += batch
            if len(batch) < page:
                return rows
            offset += page


    def _row_payload(row, col_ids):
        return {str(col_ids[title]): row[title] for title, _ in COLUMNS if row.get(title) is not None}


    def _same(a, b):
        """Remote numbers can come back as 198.0 for 198 -- compare numerically."""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(a - b) < 1e-9
        if isinstance(b, (int, float)) and isinstance(a, str):
            try:
                return abs(float(a) - b) < 1e-9
            except ValueError:
                return False
        return a == b


    def upsert_rows(nc, table_id, col_ids, rows):
        """Create or update rows by Key. Returns (created, updated, unchanged)."""
        key_col = col_ids["Key"]
        existing = {}
        for remote in _all_rows(nc, table_id):
            values = {cell["columnId"]: cell["value"] for cell in remote.get("data", [])}
            if values.get(key_col) is not None:
                existing[values[key_col]] = (remote["id"], values)
        created = updated = unchanged = 0
        for row in rows:
            payload = _row_payload(row, col_ids)
            if row["Key"] not in existing:
                nc.tables("POST", f"/tables/{table_id}/rows", {"data": payload})
                created += 1
                continue
            row_id, values = existing[row["Key"]]
            if all(_same(values.get(int(cid)), value) for cid, value in payload.items()):
                unchanged += 1
                continue
            nc.tables("PUT", f"/rows/{row_id}", {"data": payload})
            updated += 1
        return created, updated, unchanged


    def view_settings(col_ids, task, required):
        """Body for PUT /views/{id}, in the shapes Tables 2.3's ViewUpdateInput
        accepts (read from its source): columnSettings [{columnId, order}],
        filter [[{columnId, operator, value}]] (groups OR-ed, entries AND-ed),
        sort [{columnId, mode: ASC|DESC}] -- real arrays, not JSON strings
        (the deprecated "columns" key breaks when given a string)."""
        filters = [{"columnId": col_ids["Task"], "operator": "is-equal", "value": task}]
        filters += [{"columnId": col_ids[column], "operator": "is-equal", "value": value}
                    for column, value in required.items()]
        shown = [title for title, _ in COLUMNS if title != "Key"]
        return {
            "columnSettings": [{"columnId": col_ids[title], "order": i} for i, title in enumerate(shown)],
            "filter": [filters],
            "sort": [{"columnId": col_ids["Score %"], "mode": "DESC"}],
        }


    def ensure_views(nc, table_id, col_ids):
        """Create missing views, and (re)apply every view's settings each time,
        so a view left half-configured by an earlier failure gets repaired."""
        existing = {v["title"]: v["id"] for v in nc.tables("GET", f"/tables/{table_id}/views") or []}
        for title, emoji, task, required in VIEWS:
            view_id = existing.get(title)
            if view_id is None:
                view_id = nc.tables("POST", f"/tables/{table_id}/views", {"title": title, "emoji": emoji})["id"]
            nc.tables("PUT", f"/views/{view_id}", {"data": view_settings(col_ids, task, required)})


    def table_layout(col_ids):
        """Body for the OCS v2 PUT /tables/{id}: the table's own column order
        (COLUMNS order, Key first) and default sort (task, then score desc).
        The v1 API has no way to set these; without it the base table shows
        columns in an arbitrary order."""
        return {
            "columnSettings": [{"columnId": col_ids[title], "order": i} for i, (title, _) in enumerate(COLUMNS)],
            "sort": [{"columnId": col_ids["Task"], "mode": "ASC"}, {"columnId": col_ids["Score %"], "mode": "DESC"}],
        }


    def ensure_table_layout(nc, table_id, col_ids):
        nc.request("PUT", f"{TABLES_OCS_API}/tables/{table_id}", body=table_layout(col_ids))


    def ensure_share(nc, table_id, user):
        shares = nc.tables("GET", f"/tables/{table_id}/shares") or []
        if any(s.get("receiver") == user for s in shares):
            return
        nc.tables("POST", f"/tables/{table_id}/shares", {
            "receiver": user, "receiverType": "user", "permissionRead": True,
            "permissionCreate": False, "permissionUpdate": False,
            "permissionDelete": False, "permissionManage": False,
        })


    def publish(nc, files, rows, share_with=None):
        nc.ensure_folder(FOLDER)
        for rel in sorted(files):
            parent = os.path.dirname(rel)
            if parent:
                nc.ensure_folder(f"{FOLDER}/{parent}")
            nc.put_file(f"{FOLDER}/{rel}", files[rel])
        for rel in STALE_FILES:
            if rel not in files:
                nc.delete_file(f"{FOLDER}/{rel}")
        table_id = ensure_table(nc)
        col_ids = ensure_columns(nc, table_id)
        counts = upsert_rows(nc, table_id, col_ids, rows)
        ensure_table_layout(nc, table_id, col_ids)
        ensure_views(nc, table_id, col_ids)
        if share_with:
            ensure_share(nc, table_id, share_with)
        return table_id, counts


    def main(argv=None):
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--dry-run", metavar="DIR", help="render into DIR instead of publishing")
        parser.add_argument("--results-root", default=RESULTS_ROOT)
        parser.add_argument("--findings", default=FINDINGS_FILE)
        args = parser.parse_args(argv)

        findings = None
        if os.path.exists(args.findings):
            with open(args.findings) as fh:
                findings = fh.read()
        generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        files, rows = build_files(collect(args.results_root), findings, generated)

        if args.dry_run:
            for rel, content in files.items():
                path = os.path.join(args.dry_run, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(content)
            print(f"dry run: {len(files)} files, {len(rows)} table rows -> {args.dry_run}")
            return 0

        env = os.environ
        missing = [k for k in ("NEXTCLOUD_EVAL_REPORTS_URL", "NEXTCLOUD_EVAL_REPORTS_USER",
                               "NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD") if not env.get(k)]
        if missing:
            print(f"publish: not configured, missing {', '.join(missing)}", file=sys.stderr)
            return 2
        nc = Nextcloud(env["NEXTCLOUD_EVAL_REPORTS_URL"], env["NEXTCLOUD_EVAL_REPORTS_USER"],
                       env["NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD"])
        try:
            table_id, (created, updated, unchanged) = publish(
                nc, files, rows, env.get("NEXTCLOUD_EVAL_TABLE_SHARE_WITH") or None)
        except NextcloudError as err:
            print(f"publish FAILED: {err}", file=sys.stderr)
            return 1
        print(f"published {len(files)} files to {FOLDER}/; table '{TABLE_TITLE}' (id {table_id}): "
              f"{created} rows created, {updated} updated, {unchanged} unchanged")
        return 0


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/publish.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/publish.py | cut -d' ' -f1"
    expect: "18dbc52fde20bd504ec7996944a4ebb0c394c551ce28a31f06639835a8477463"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/publish.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-06i-mock-nextcloud

```yaml
id: eval-runner-06i-mock-nextcloud
title: Add the selftest stand-in Nextcloud
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/mock_nextcloud.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """In-memory stand-in for the slice of Nextcloud that publish.py uses, for
    `eval-run selftest`: WebDAV MKCOL/PUT/DELETE under /remote.php/dav/files/<user>/,
    and the Tables v1 API (tables, columns, rows, views, shares). Checks HTTP
    basic auth against MOCK_NC_USER / MOCK_NC_PASSWORD.

    GET /_mock/state returns everything stored, so selftest_checks.py can
    assert on it. Listens on 127.0.0.1 only (MOCK_NC_PORT, default 18090).
    """

    import base64
    import json
    import os
    import re
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    PORT = int(os.environ.get("MOCK_NC_PORT", "18090"))
    USER = os.environ.get("MOCK_NC_USER", "eval-reports")
    PASSWORD = os.environ.get("MOCK_NC_PASSWORD", "selftest")
    API = "/index.php/apps/tables/api/1"
    OCS_API = "/ocs/v2.php/apps/tables/api/2"

    _lock = threading.Lock()
    STATE = {}
    _ids = {"n": 0}


    def reset():
        """Empty all stored state (unit tests reuse route() in-process)."""
        STATE.clear()
        STATE.update({"folders": [], "files": {}, "deleted": [], "tables": [], "columns": [], "rows": [],
                      "views": [], "shares": [], "requests": 0})
        _ids["n"] = 0


    reset()


    def stored_content(body):
        """Text files as text; anything else (leaderboard.xlsx) as a marker that
        records its size and whether it's a zip container."""
        try:
            return body.decode()
        except UnicodeDecodeError:
            return f"<binary {len(body)} bytes{' zip' if body[:2] == b'PK' else ''}>"


    def _next_id():
        _ids["n"] += 1
        return _ids["n"]


    FILTER_OPERATORS = {"begins-with", "ends-with", "contains", "contains-item", "does-not-contain", "is-equal",
                        "is-not-equal", "is-greater-than", "is-greater-than-or-equal", "is-lower-than",
                        "is-lower-than-or-equal", "is-empty"}


    def view_update_problem(data):
        """Mirror of Tables 2.3 ViewUpdateInput's input contract (the real one
        answers HTTP 500 for these): None if acceptable, else what's wrong."""
        if "columns" in data and isinstance(data["columns"], str):
            return "deprecated 'columns' given as a string (foreach on string)"
        settings = data.get("columnSettings")
        if settings is not None and not (isinstance(settings, list)
                                         and all(isinstance(c, dict) and "columnId" in c for c in settings)):
            return "columnSettings must be a list of {columnId, order}"
        for group in data.get("filter") or []:
            for f in group:
                if not {"columnId", "operator", "value"} <= set(f) or f["operator"] not in FILTER_OPERATORS:
                    return f"bad filter entry {f}"
        for rule in data.get("sort") or []:
            if not isinstance(rule, dict) or rule.get("mode") not in ("ASC", "DESC") or "columnId" not in rule:
                return f"bad sort rule {rule}"
        return None


    def ocs_route(method, path, body):
        """Tables OCS v2: only PUT /tables/{id} (column order + sort)."""
        m = re.fullmatch(r"/tables/(\d+)", path)
        if not (m and method == "PUT"):
            return 404, {"ocs": {"meta": {"status": "failure"}, "data": []}}
        table = next((t for t in STATE["tables"] if t["id"] == int(m.group(1))), None)
        if table is None:
            return 404, {"ocs": {"meta": {"status": "failure"}, "data": []}}
        problem = view_update_problem({k: body.get(k) for k in ("columnSettings", "sort") if k in body})
        if problem:
            return 500, {"ocs": {"meta": {"status": "failure", "message": problem}, "data": []}}
        table.update({k: body[k] for k in ("columnSettings", "sort") if k in body})
        return 200, {"ocs": {"meta": {"status": "ok"}, "data": table}}


    def route(method, path, body):
        """Tables v1 routing: (status, json body). Caller holds _lock if threaded."""
        m = re.fullmatch(r"/tables", path)
        if m and method == "GET":
            return 200, STATE["tables"]
        if m and method == "POST":
            table = {"id": _next_id(), "title": body["title"], "emoji": body.get("emoji")}
            STATE["tables"].append(table)
            return 200, table
        m = re.fullmatch(r"/tables/(\d+)/(columns|rows|views|shares)", path)
        if m:
            table_id, kind = int(m.group(1)), m.group(2)
            if method == "GET":
                return 200, [x for x in STATE[kind] if x["tableId"] == table_id]
            if kind == "columns":
                item = {"id": _next_id(), "tableId": table_id, **body}
            elif kind == "rows":
                data = [{"columnId": int(k), "value": v} for k, v in body["data"].items()]
                item = {"id": _next_id(), "tableId": table_id, "data": data}
            elif kind == "views":
                item = {"id": _next_id(), "tableId": table_id, "title": body["title"], "emoji": body.get("emoji")}
            else:
                item = {"id": _next_id(), "tableId": table_id, **body}
            STATE[kind].append(item)
            return 200, item
        m = re.fullmatch(r"/rows/(\d+)", path)
        if m and method == "PUT":
            row = next((r for r in STATE["rows"] if r["id"] == int(m.group(1))), None)
            if row is None:
                return 404, {"message": "no such row"}
            cells = {c["columnId"]: c["value"] for c in row["data"]}
            cells.update({int(k): v for k, v in body["data"].items()})
            row["data"] = [{"columnId": k, "value": v} for k, v in cells.items()]
            return 200, row
        m = re.fullmatch(r"/views/(\d+)", path)
        if m and method == "PUT":
            view = next((v for v in STATE["views"] if v["id"] == int(m.group(1))), None)
            if view is None:
                return 404, {"message": "no such view"}
            problem = view_update_problem(body.get("data", {}))
            if problem:
                return 500, {"message": problem}
            view.update(body["data"])
            return 200, view
        return 404, {"message": f"no route {method} {path}"}


    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body=None):
            data = b"" if body is None else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self):
            expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
            if self.headers.get("Authorization") != expected:
                self._send(401, {"message": "unauthorised"})
                return False
            return True

        def _body(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            return raw

        def _json(self):
            raw = self._body()
            return json.loads(raw) if raw else {}

        def _dav_path(self):
            prefix = f"/remote.php/dav/files/{USER}/"
            return self.path[len(prefix):] if self.path.startswith(prefix) else None

        def do_MKCOL(self):  # noqa: N802 (HTTP verb)
            if not self._authorised():
                return
            path = self._dav_path()
            with _lock:
                STATE["requests"] += 1
                if path in STATE["folders"]:
                    self._send(405)
                    return
                STATE["folders"].append(path)
            self._send(201)

        def do_PUT(self):  # noqa: N802
            if not self._authorised():
                return
            path = self._dav_path()
            if path is not None:
                body = self._body()
                parent = path.rsplit("/", 1)[0]
                with _lock:
                    STATE["requests"] += 1
                    if parent not in STATE["folders"]:
                        self._send(409, {"message": f"parent {parent} missing"})
                        return
                    existed = path in STATE["files"]
                    STATE["files"][path] = stored_content(body)
                self._send(204 if existed else 201)
                return
            self._tables("PUT", self._json())

        def do_DELETE(self):  # noqa: N802
            if not self._authorised():
                return
            path = self._dav_path()
            with _lock:
                STATE["requests"] += 1
                STATE["deleted"].append(path)
                existed = STATE["files"].pop(path, None) is not None
            self._send(204 if existed else 404)

        def do_GET(self):  # noqa: N802
            if self.path == "/_mock/state":
                with _lock:
                    self._send(200, STATE)
                return
            if not self._authorised():
                return
            self._tables("GET", None)

        def do_POST(self):  # noqa: N802
            if not self._authorised():
                return
            self._tables("POST", self._json())

        def _tables(self, method, body):
            path = self.path.split("?", 1)[0]
            if path.startswith(OCS_API):
                with _lock:
                    STATE["requests"] += 1
                    code, result = ocs_route(method, path[len(OCS_API):], body or {})
                self._send(code, result)
                return
            if not path.startswith(API):
                self._send(404, {"message": "not found"})
                return
            sub = path[len(API):]
            with _lock:
                STATE["requests"] += 1
                code, result = route(method, sub, body or {})
            self._send(code, result)

        def log_message(self, *args):
            """Silence per-request access logging."""


    if __name__ == "__main__":
        # Plain HTTP on loopback inside a throwaway test container.
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()  # NOSONAR

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/mock_nextcloud.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/mock_nextcloud.py | cut -d' ' -f1"
    expect: "cce4634eda90bd82a1643444fa5908a7add10b5f9ef4523d88cb54760d1b6448"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/mock_nextcloud.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-06j-test-publish

```yaml
id: eval-runner-06j-test-publish
title: Add publish unit tests
depends_on:
  - eval-runner-06h-publish
  - eval-runner-06i-mock-nextcloud
  - eval-runner-06g-test-summarize

change: |
  Create terraform/lxc/ansible/files/eval-runner/test_publish.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Unit tests for publish.py (synthetic results, in-process fake Nextcloud).
    python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
    """

    import io
    import json
    import os
    import tempfile
    import unittest

    import mock_nextcloud
    import publish

    try:
        import openpyxl
    except ImportError:  # the image has it; locally: pip install openpyxl==3.1.5 in a venv
        openpyxl = None
    import summarize
    from test_summarize import gpqa_rows, ifeval_rows, write_run


    class FakeNextcloud:
        """publish.Nextcloud's interface, backed by mock_nextcloud's state and routing."""

        def __init__(self):
            mock_nextcloud.reset()
            self.state = mock_nextcloud.STATE
            self.calls = []

        def ensure_folder(self, rel):
            parts = rel.strip("/").split("/")
            for i in range(1, len(parts) + 1):
                path = "/".join(parts[:i])
                if path not in self.state["folders"]:
                    self.state["folders"].append(path)

        def request(self, method, path, body=None):
            self.calls.append((method, path))
            assert path.startswith(mock_nextcloud.OCS_API), path
            code, result = mock_nextcloud.ocs_route(method, path[len(mock_nextcloud.OCS_API):], body or {})
            if code != 200:
                raise publish.NextcloudError(f"{method} {path} -> {code} {result}")
            return result

        def put_file(self, rel, content):
            assert os.path.dirname(rel) in self.state["folders"], rel
            self.state["files"][rel] = mock_nextcloud.stored_content(content)

        def delete_file(self, rel):
            self.state["deleted"].append(rel)
            self.state["files"].pop(rel, None)

        def tables(self, method, path, body=None):
            self.calls.append((method, path))
            code, result = mock_nextcloud.route(method, path.split("?", 1)[0], body or {})
            if code != 200:
                raise publish.NextcloudError(f"{method} {path} -> {code} {result}")
            return result


    def make_tree(root):
        """One eval-runner run (with run.json) and two historical sources (one excluded)."""
        run_dir = write_run(root, "glm-5.3-flash-both-20261002T000000Z", ["gpqa", "ifeval"],
                            gpqa_rows=gpqa_rows(["(A)", "", "(B)"]), ifeval_rows=ifeval_rows(["ok", ""]),
                            run_json=False)
        with open(os.path.join(run_dir, "run.json"), "w") as fh:
            json.dump({"run": os.path.basename(run_dir), "note": "reasoning_effort=high", "created_utc": "20261002T000000Z",
                       "fingerprint": "abcd" * 16, "limit": None, "concurrency": 1, "lm_eval_version": "0.4.12",
                       "server": {"model_id": "glm-5.3-flash", "props": {
                           "model_path": "/m/GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf",
                           "build_info": "b11309-a4d880fd5", "n_ctx": 131072,
                           "params": {"temperature": 1.0, "top_p": 0.95}}}}, fh)
        hist = os.path.join(root, summarize.HISTORICAL_DIR)
        os.makedirs(hist)
        write_run(hist, "qwen36-35b-redo", ["gpqa", "ifeval"], gpqa_rows=gpqa_rows(["(A)", ""]),
                  ifeval_rows=ifeval_rows(["ok"]), run_json=False)
        write_run(hist, "qwen36-35b", ["ifeval"], ifeval_rows=ifeval_rows(["x"]), run_json=False,
                  config={"limit": None, "gen_kwargs": {}, "model_args": {"model": "eval-qwen36", "base_url": "http://f:11434/v1"}})
        return run_dir


    def add_32k_run(root):
        """A full GPQA run at the 32k budget: its own series, not comparable with 8k."""
        write_run(root, "glm-5.3-flash-gpqa-32k-20261003T000000Z", ["gpqa"], gpqa_rows=gpqa_rows(["(A)", "(B)"]),
                  run_json=False, config={"limit": None, "gen_kwargs": {"max_gen_toks": 32768},
                                          "model_args": {"model": "glm-5.3-flash"}})


    class CollectTest(unittest.TestCase):
        def test_rows_from_runs_and_history(self):
            with tempfile.TemporaryDirectory() as root:
                make_tree(root)
                rows = [r for _, _, _, rs in publish.collect(root) for r in rs]
            by_key = {r["Key"]: r for r in rows}
            self.assertEqual(len(rows), 5)
            glm = by_key["runs/glm-5.3-flash-both-20261002T000000Z/gpqa_diamond_cot_zeroshot"]
            self.assertEqual(glm["Model"], "glm-5.3-flash")
            self.assertEqual(glm["Runtime"], "llama.cpp b11309-a4d880fd5")
            self.assertEqual(glm["Model file / tag"], "GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf")
            self.assertEqual(glm["Note"], "reasoning_effort=high")
            self.assertEqual(glm["Date"], "2026-10-02")
            self.assertEqual((glm["Score %"], glm["Empty answers"], glm["Unparsed"]), (50.0, 1, 1))
            self.assertEqual(glm["Empty %"], 33.3)
            self.assertEqual(glm["Comparable"], "yes")
            bug6 = [r for r in rows if r["Run"] == "qwen36-35b"][0]
            self.assertEqual(bug6["Comparable"], "no")
            self.assertIn("Bug 6", bug6["Why not comparable"])
            self.assertEqual(bug6["Runtime"], "Ollama")
            self.assertTrue(bug6["Key"].startswith("historical/qwen36-35b/ifeval/"))


    class RenderTest(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory()
            make_tree(self.tmp.name)
            self.files, self.rows = publish.build_files(publish.collect(self.tmp.name), "# findings\n", "NOW")

        def tearDown(self):
            self.tmp.cleanup()

        def test_expected_files(self):
            self.assertIn("leaderboard.md", self.files)
            self.assertNotIn("leaderboard.csv", self.files)
            if openpyxl:
                self.assertIn("leaderboard.xlsx", self.files)
            self.assertEqual(self.files["findings.md"], b"# findings\n")
            self.assertIn("runs/glm-5.3-flash-both-20261002T000000Z/report.md", self.files)
            self.assertIn("historical/qwen36-35b/manifest.json", self.files)
            self.assertFalse(any("samples_" in name for name in self.files))

        def test_markdown_tables_have_consistent_columns(self):
            for name, content in self.files.items():
                if not name.endswith(".md"):
                    continue
                header_cols = None
                for line in content.decode().splitlines():
                    if not line.startswith("|"):
                        header_cols = None
                        continue
                    cols = line.count("|")
                    header_cols = header_cols or cols
                    self.assertEqual(cols, header_cols, f"{name}: {line}")

        def test_leaderboard_ranks_and_lists_excluded(self):
            board = self.files["leaderboard.md"].decode()
            self.assertIn("| 1 | glm-5.3-flash | 50.00% |", board)
            self.assertIn("## Not comparable", board)
            self.assertIn("no max_gen_toks=8192", board)

        def test_manifest_follows_convention(self):
            manifest = json.loads(self.files["runs/glm-5.3-flash-both-20261002T000000Z/manifest.json"])
            for key in ("project", "run_id", "started_at", "finished_at", "summary"):
                self.assertIn(key, manifest)
            self.assertEqual(manifest["project"], "eval-runner")

        def test_markdown_tables_stay_narrow(self):
            for line in self.files["leaderboard.md"].decode().splitlines():
                if line.startswith("|"):
                    self.assertLessEqual(line.count("|") - 1, 6, line)

        @unittest.skipUnless(openpyxl, "openpyxl not installed")
        def test_xlsx_sheets_rank_and_hold_every_row(self):
            wb = openpyxl.load_workbook(io.BytesIO(self.files["leaderboard.xlsx"]))
            self.assertEqual(wb.sheetnames, ["GPQA (8k)", "IFEval (8k)", "All results", "Notes"])
            gpqa = wb["GPQA (8k)"]
            self.assertEqual(gpqa["A1"].value, "Rank")
            self.assertEqual(gpqa["B2"].value, "glm-5.3-flash")
            self.assertEqual(gpqa["C2"].value, 50.0)
            self.assertEqual(gpqa["C2"].number_format, '0.00"%"')
            self.assertEqual(gpqa.freeze_panes, "C2")
            self.assertIsNotNone(gpqa.auto_filter.ref)
            everything = wb["All results"]
            self.assertEqual(everything.max_row, 1 + len(self.rows))
            self.assertEqual([c.value for c in everything[1]], [t for t, _ in publish.COLUMNS if t != "Key"])


    class SeriesTest(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory()
            make_tree(self.tmp.name)
            add_32k_run(self.tmp.name)
            self.files, self.rows = publish.build_files(publish.collect(self.tmp.name), None, "NOW")

        def tearDown(self):
            self.tmp.cleanup()

        def test_32k_row_is_its_own_series(self):
            row = next(r for r in self.rows if "32k" in r["Run"])
            self.assertEqual((row["Series"], row["Comparable"], row["Token budget"]), ("32k", "no", 32768))
            self.assertIn("separate 32k series", row["Why not comparable"])

        def test_leaderboard_ranks_32k_separately(self):
            board = self.files["leaderboard.md"].decode()
            self.assertIn("## GPQA diamond: 32k token budget series, not comparable with 8k", board)
            self.assertNotIn("## IFEval: 32k", board)
            not_comparable = board.split("## Not comparable")[1]
            self.assertNotIn("separate 32k series", not_comparable)

        @unittest.skipUnless(openpyxl, "openpyxl not installed")
        def test_xlsx_has_32k_sheet(self):
            wb = openpyxl.load_workbook(io.BytesIO(self.files["leaderboard.xlsx"]))
            self.assertEqual(wb.sheetnames, ["GPQA (8k)", "GPQA (32k)", "IFEval (8k)", "All results", "Notes"])
            self.assertEqual(wb["GPQA (32k)"].max_row, 2)

        def test_32k_views_filter_on_series(self):
            col_ids = {t: i for i, (t, _) in enumerate(publish.COLUMNS)}
            settings = publish.view_settings(col_ids, "GPQA diamond", {"Series": "32k"})
            self.assertIn({"columnId": col_ids["Series"], "operator": "is-equal", "value": "32k"}, settings["filter"][0])


    class PublishTest(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory()
            make_tree(self.tmp.name)
            self.files, self.rows = publish.build_files(publish.collect(self.tmp.name), None, "NOW")
            self.nc = FakeNextcloud()

        def tearDown(self):
            self.tmp.cleanup()

        def test_first_publish_creates_everything(self):
            table_id, counts = publish.publish(self.nc, self.files, self.rows, share_with="steve")
            self.assertEqual(counts, (5, 0, 0))
            state = self.nc.state
            self.assertEqual([t["title"] for t in state["tables"]], [publish.TABLE_TITLE])
            self.assertEqual([c["title"] for c in state["columns"]], [t for t, _ in publish.COLUMNS])
            self.assertEqual(len(state["rows"]), 5)
            self.assertEqual({v["title"] for v in state["views"]}, {v[0] for v in publish.VIEWS})
            view = state["views"][0]
            self.assertEqual(view["filter"][0][0]["operator"], "is-equal")
            self.assertEqual(view["sort"], [{"columnId": view["columnSettings"][2]["columnId"], "mode": "DESC"}])
            self.assertEqual(len(view["columnSettings"]), len(publish.COLUMNS) - 1)
            self.assertEqual([s["receiver"] for s in state["shares"]], ["steve"])
            self.assertIn(f"{publish.FOLDER}/leaderboard.md", state["files"])
            self.assertEqual(state["deleted"], [f"{publish.FOLDER}/leaderboard.csv"])
            table = state["tables"][0]
            key_id = next(c["id"] for c in state["columns"] if c["title"] == "Key")
            self.assertEqual(table["columnSettings"][0], {"columnId": key_id, "order": 0})
            self.assertEqual([r["mode"] for r in table["sort"]], ["ASC", "DESC"])

        def test_republish_is_idempotent(self):
            publish.publish(self.nc, self.files, self.rows, share_with="steve")
            _, counts = publish.publish(self.nc, self.files, self.rows, share_with="steve")
            self.assertEqual(counts, (0, 0, 5))
            state = self.nc.state
            self.assertEqual((len(state["tables"]), len(state["rows"]), len(state["views"]), len(state["shares"])),
                             (1, 5, len(publish.VIEWS), 1))

        def test_half_configured_view_is_repaired(self):
            table_id, _ = publish.publish(self.nc, self.files, self.rows)
            self.nc.state["views"][0].pop("filter")
            publish.publish(self.nc, self.files, self.rows)
            self.assertIn("filter", self.nc.state["views"][0])
            self.assertEqual(len(self.nc.state["views"]), len(publish.VIEWS))

        def test_mock_rejects_the_old_string_format(self):
            import mock_nextcloud
            self.assertIsNotNone(mock_nextcloud.view_update_problem({"columns": "[1,2]"}))
            self.assertIsNotNone(mock_nextcloud.view_update_problem({"sort": [{"columnId": 1, "mode": "down"}]}))
            self.assertIsNone(mock_nextcloud.view_update_problem(publish.view_settings(
                {t: i for i, (t, _) in enumerate(publish.COLUMNS)}, "IFEval", {"Comparable": "yes"})))

        def test_changed_value_updates_in_place(self):
            publish.publish(self.nc, self.files, self.rows)
            changed = [dict(r) for r in self.rows]
            changed[0]["Note"] = "edited"
            _, counts = publish.publish(self.nc, self.files, changed)
            self.assertEqual(counts, (0, 1, 4))
            self.assertEqual(len(self.nc.state["rows"]), 5)

        def test_numbers_returned_as_floats_are_unchanged(self):
            self.assertTrue(publish._same(198.0, 198))
            self.assertTrue(publish._same("43.94", 43.94))
            self.assertFalse(publish._same(43.0, 43.94))


    class ClientTest(unittest.TestCase):
        def test_network_error_becomes_nextcloud_error(self):
            import urllib.error

            def refuse(req, timeout=None):
                raise urllib.error.URLError("connection refused")
            nc = publish.Nextcloud("http://x", "u", "p", opener=refuse)
            with self.assertRaises(publish.NextcloudError):
                nc.tables("GET", "/tables")

        def test_webdav_paths_are_quoted(self):
            nc = publish.Nextcloud("https://nc/", "eval-reports", "p")
            self.assertEqual(nc._dav("Reports/eval-runner/a b.md"),
                             "/remote.php/dav/files/eval-reports/Reports/eval-runner/a%20b.md")


    class MainTest(unittest.TestCase):
        def test_dry_run_writes_files(self):
            with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
                make_tree(root)
                with unittest.mock.patch("builtins.print"):
                    rc = publish.main(["--results-root", root, "--dry-run", out, "--findings", "/nonexistent"])
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(os.path.join(out, "leaderboard.md")))

        def test_unconfigured_publish_exits_2(self):
            with tempfile.TemporaryDirectory() as root:
                with unittest.mock.patch.dict(os.environ, {}, clear=True), \
                        unittest.mock.patch("sys.stderr", new_callable=io.StringIO):
                    self.assertEqual(publish.main(["--results-root", root, "--findings", "/nonexistent"]), 2)


    if __name__ == "__main__":
        unittest.main()

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/test_publish.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/test_publish.py | cut -d' ' -f1"
    expect: "d388fd15add71e1fc4f5089793b2ecd154cb0f221cb0d4f1d84c086b29c04e47"
    critical: true
  - id: unit-tests
    cmd: "python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner/ -p 'test_*.py' 2>&1 | tail -1"
    expect: "OK, or OK (skipped=N) where openpyxl/rapidfuzz are not installed"
    critical: true
```

### eval-runner-11a-wrapper-common

```yaml
id: eval-runner-11a-wrapper-common
title: Add the shared wrapper results writer
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/wrapper_common.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Shared by eval-runner's own benchmark wrappers (bfcl_run.py,
    agentbench_run.py, repobench_run.py).

    Each wrapper runs one benchmark against the server recorded in the run's
    run.json, then writes <run>/<harness>/results_<stamp>.json in the same
    shape as lm_eval's results files, so summarize.py, publish.py and the
    Nextcloud table treat every benchmark alike:

      {"results": {task: {metric: value, ..., "empty,none": n, "errors,none": n}},
       "n-samples": {task: {"original": N, "effective": n}},
       "config": {"limit": ..., "model_args": {...}, "gen_kwargs": {...},
                  "eval_runner": {"harness", "version", "series", "exclusion",
                                  "runtime", "origin", "note"}},
       "date": <unix time>}

    config.eval_runner decides comparability (summarize.exclusion_reason):
    series is the task's STANDARD_SERIES name for a comparable result, and
    exclusion explains why a full run is not comparable (None if it is).
    """

    import datetime
    import json
    import os
    import time


    def load_record(run_dir):
        with open(os.path.join(run_dir, "run.json")) as fh:
            return json.load(fh)


    def server(record):
        """(OpenAI-compatible /v1 base URL, served model id, API key)."""
        base = record["server"]["base_url"].rstrip("/")
        return f"{base}/v1", record["server"]["model_id"], os.environ.get("OPENAI_API_KEY", "")


    def runtime(record):
        props = (record.get("server") or {}).get("props") or {}
        return f"llama.cpp {props.get('build_info') or ''}".strip() if props else "OpenAI-compatible server"


    def now_stamp():
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")


    def write_results(out_dir, task, metrics, n_effective, n_original, *, limit, model, base_url,
                      harness, version, series, exclusion=None, max_gen_toks=None, runtime=None,
                      origin=None, note=None, date=None, stamp=None):
        """Write one lm_eval-shaped results file; return its path."""
        os.makedirs(out_dir, exist_ok=True)
        data = {
            "results": {task: metrics},
            "n-samples": {task: {"original": n_original, "effective": n_effective}},
            "config": {
                "limit": limit,
                "model_args": {"model": model, "base_url": base_url},
                "gen_kwargs": {"max_gen_toks": max_gen_toks} if max_gen_toks else {},
                "eval_runner": {"harness": harness, "version": version, "series": series,
                                "exclusion": exclusion, "runtime": runtime, "origin": origin, "note": note},
            },
            "date": date if date is not None else time.time(),
        }
        path = os.path.join(out_dir, f"results_{stamp or now_stamp()}.json")
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        return path

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/wrapper_common.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/wrapper_common.py | cut -d' ' -f1"
    expect: "89e086e5fec47303396bc48d3ec1be90a49cc360f5de1708ab28c1eb9a4bdac9"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/wrapper_common.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-11b-bfcl-run

```yaml
id: eval-runner-11b-bfcl-run
title: Add the BFCL wrapper
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/bfcl_run.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """BFCL (Berkeley Function Calling Leaderboard) for eval-runner.

    Runs BFCL v3's "simple" category (400 single-call Python cases) with
    bfcl-eval 2025.8.6.2 against the server in <run>/run.json -- the same
    category, package version, default temperature (0.001) and native
    function-calling request shape as every historical BFCL number on
    framework. There, each model had its own copy-pasted handler edited into
    site-packages; here one generic handler ("eval-runner-FC") is registered
    at start-up and pointed at whatever model the server is serving. Its
    request is the historical handlers' (messages, model, temperature, tools;
    no max_tokens, so the server's default length applies).

    Usage (inside the eval-runner-bfcl image, via `runmeta.py exec`):
      bfcl_run.py <run_dir>

    Output, all under <run_dir>/bfcl/:
      result/eval-runner-FC/BFCL_v3_simple_result.json   raw answers (BFCL's own)
      score/eval-runner-FC/BFCL_v3_simple_score.json     per-case verdicts
      results_<stamp>.json                               the eval-runner summary

    Resuming re-runs only the cases with no answer yet, plus any that failed
    with an inference error (a timeout, say). With a limit (--pilot), an evenly
    spaced subset of the 400 cases is run and scored.
    """

    import json
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import wrapper_common as wc  # noqa: E402

    TASK = "bfcl_simple"
    CATEGORY = "simple"
    TOTAL_CASES = 400
    MODEL_NAME = "eval-runner-FC"  # no "_": BFCL's checker maps "_" back to "/"
    VERSION = "2025.8.6.2"
    SERIES = "v3 simple"
    TEMPERATURE = "0.001"  # `bfcl generate`'s default; no historical run changed it
    RESULT_FILE = "BFCL_v3_simple_result.json"
    ERROR_PREFIX = "Error during inference"


    def pilot_ids(limit, total=TOTAL_CASES):
        """An evenly spaced subset of case ids (the earlier BFCL pilots used every 20th)."""
        stride = max(1, total // limit)
        return [f"{CATEGORY}_{i * stride}" for i in range(min(limit, total))]


    def drop_errored(path):
        """Remove inference-error entries from a result file so a resume retries
        them (BFCL itself treats any existing entry as done). Returns how many."""
        if not os.path.exists(path):
            return 0
        with open(path) as fh:
            entries = [json.loads(line) for line in fh if line.strip()]
        keep = [e for e in entries if not str(e.get("result", "")).startswith(ERROR_PREFIX)]
        if len(keep) != len(entries):
            with open(path, "w") as fh:
                for entry in keep:
                    fh.write(json.dumps(entry) + "\n")
        return len(entries) - len(keep)


    def response_counts(entries):
        """(empty, errors): answers with neither a tool call nor text, and
        requests that failed outright."""
        empty = sum(1 for e in entries if e.get("result") in ("", [], None))
        errors = sum(1 for e in entries if str(e.get("result", "")).startswith(ERROR_PREFIX))
        return empty, errors


    def register(base_url, model_id, api_key):
        """Add the generic eval-runner-FC model to BFCL's model table."""
        from bfcl_eval.constants import model_config as mc
        from bfcl_eval.model_handler.api_inference.openai_completion import OpenAICompletionsHandler
        from openai import OpenAI

        class EvalRunnerFCHandler(OpenAICompletionsHandler):
            def __init__(self, model_name, temperature):
                super().__init__(model_name, temperature)
                self.client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY", timeout=3600)

            def _query_FC(self, inference_data):  # noqa: N802 (BFCL's name)
                message = inference_data["message"]
                tools = inference_data["tools"]
                inference_data["inference_input_log"] = {"message": repr(message), "tools": tools}
                kwargs = {"messages": message, "model": model_id, "temperature": self.temperature}
                if len(tools) > 0:
                    kwargs["tools"] = tools
                return self.generate_with_backoff(**kwargs)

        mc.MODEL_CONFIG_MAPPING[MODEL_NAME] = mc.ModelConfig(
            model_name=MODEL_NAME, display_name=f"eval-runner: {model_id}", url="local", org="local",
            license="n/a", model_handler=EvalRunnerFCHandler, input_price=None, output_price=None,
            is_fc_model=True, underscore_to_dot=True,
        )


    def generate(limit, project_root):
        import typer
        from bfcl_eval.__main__ import cli

        args = ["generate", "--model", MODEL_NAME, "--test-category", CATEGORY,
                "--temperature", TEMPERATURE, "--num-threads", "1"]
        if limit:
            with open(os.path.join(project_root, "test_case_ids_to_generate.json"), "w") as fh:
                json.dump({CATEGORY: pilot_ids(limit)}, fh)
            args.append("--run-ids")
        typer.main.get_command(cli)(args, standalone_mode=False)


    def score():
        """Score whatever has been generated with BFCL's own AST checker (the
        path `bfcl evaluate` takes for "simple"), restricted to the generated
        cases so a pilot subset scores too. Returns (accuracy, total, entries)."""
        from bfcl_eval.constants.eval_config import POSSIBLE_ANSWER_PATH, PROMPT_PATH, RESULT_PATH, SCORE_PATH
        from bfcl_eval.eval_checker.eval_runner import ast_file_runner, get_handler
        from bfcl_eval.utils import find_file_with_suffix, load_file

        entries = load_file(RESULT_PATH / MODEL_NAME / RESULT_FILE, sort_by_id=True)
        ids = {e["id"] for e in entries}
        prompt = [p for p in load_file(find_file_with_suffix(PROMPT_PATH, CATEGORY), sort_by_id=True) if p["id"] in ids]
        answers = [a for a in load_file(find_file_with_suffix(POSSIBLE_ANSWER_PATH, CATEGORY), sort_by_id=True)
                   if a["id"] in ids]
        accuracy, total = ast_file_runner(get_handler(MODEL_NAME), entries, prompt, answers, "Python",
                                          CATEGORY, MODEL_NAME, SCORE_PATH)
        return accuracy, total, entries


    def main(argv=None):
        argv = argv if argv is not None else sys.argv[1:]
        if len(argv) != 1:
            print("usage: bfcl_run.py <run_dir>", file=sys.stderr)
            return 2
        run_dir = argv[0]
        record = wc.load_record(run_dir)
        project_root = os.path.join(run_dir, "bfcl")
        os.makedirs(project_root, exist_ok=True)
        # BFCL resolves its result/score paths from this at import time.
        os.environ["BFCL_PROJECT_ROOT"] = project_root

        base_url, model_id, api_key = wc.server(record)
        register(base_url, model_id, api_key)
        retried = drop_errored(os.path.join(project_root, "result", MODEL_NAME, RESULT_FILE))
        if retried:
            print(f"bfcl_run: retrying {retried} cases that failed with an inference error")
        limit = record.get("limit")
        generate(limit, project_root)
        accuracy, total, entries = score()
        empty, errors = response_counts(entries)
        path = wc.write_results(
            project_root, TASK,
            {"accuracy,none": accuracy, "correct,none": round(accuracy * total), "empty,none": empty,
             "errors,none": errors},
            total, TOTAL_CASES, limit=limit, model=model_id, base_url=base_url, harness="bfcl",
            version=VERSION, series=SERIES, runtime=wc.runtime(record),
        )
        print(f"bfcl_run: accuracy {accuracy:.4f} on {total} cases (empty {empty}, errors {errors}) -> {path}")
        return 0


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/bfcl_run.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/bfcl_run.py | cut -d' ' -f1"
    expect: "4678968c8b26a596eb3562152d3795732aac9a4b433b9de2227f49627446d931"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/bfcl_run.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-11c-agentbench-run

```yaml
id: eval-runner-11c-agentbench-run
title: Add the AgentBench wrapper
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/agentbench_run.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """AgentBench os-std for eval-runner.

    Runs AgentBench's os-std task (Eugleo/agent-bench at the pinned commit:
    the prompt-injection variant of OS interaction, 800 episodes = 14 base
    tasks x injection variants) on 100 episodes sampled with seed 42 -- the
    same sample, agent settings (temperature 0, max_tokens 3072, HTTP agent,
    role_content_dict prompter) and success metric as every historical
    AgentBench number. Each episode runs in a throwaway local-os/default
    container on the CT's Docker (socket mounted by `eval-run agentbench`),
    with networking disabled; see Dockerfile.agentbench-sandbox for why that
    doesn't change what the tasks see.

    Usage (inside the eval-runner-agentbench image, via `runmeta.py exec`):
      agentbench_run.py <run_dir>

    Output, under <run_dir>/agentbench/:
      outputs/eval-runner/os-std/runs.jsonl, overall.json   AgentBench's own
      results_<stamp>.json                                  the eval-runner summary

    Resuming re-runs only the episodes not yet in runs.jsonl (AgentBench's
    assigner does this itself for an existing output folder).
    """

    import json
    import os
    import signal
    import subprocess
    import sys
    import time
    import urllib.request

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import wrapper_common as wc  # noqa: E402

    AGENTBENCH_ROOT = "/opt/agentbench"
    TASK = "agentbench_os_std"
    AB_TASK = "os-std"
    AGENT = "eval-runner"
    SAMPLE_LIMIT = 100
    SAMPLE_SEED = 42
    TOTAL_EPISODES = 800
    MAX_TOKENS = 3072
    VERSION = "0cfef97+eval-runner.patch"
    SERIES = "100 seeded"
    CONTROLLER = "http://localhost:5000/api"
    FAILED_STATUSES = ("unknown", "task error")


    def agent_config(chat_url, model_id):
        """AgentBench agent definition, as the historical per-model files on
        garuda, except the API key comes from the environment at request time."""
        return {AGENT: {
            "module": "src.client.agents.HTTPAgent",
            "parameters": {
                "name": AGENT,
                "url": chat_url,
                "headers": {"Content-Type": "application/json", "Authorization": "Bearer ${OPENAI_API_KEY}"},
                "body": {"model": model_id, "temperature": 0, "max_tokens": MAX_TOKENS},
                "prompter": {"name": "role_content_dict", "args": {"agent_role": "assistant"}},
                "return_format": "{response[choices][0][message][content]}",
            },
        }}


    def assignment_config(agent_file, output_dir):
        return {
            "definition": {
                "task": {
                    "overwrite": {"module": "src.client.TaskClient",
                                  "parameters": {"controller_address": CONTROLLER}},
                    "import": os.path.join(AGENTBENCH_ROOT, "configs/tasks/task_assembly.yaml"),
                },
                "agent": {"import": [agent_file]},
            },
            "concurrency": {"task": {AB_TASK: 1}, "agent": {AGENT: 1}},
            "assignments": [{"agent": [AGENT], "task": [AB_TASK]}],
            "output": output_dir,
        }


    def episode_counts(runs_path):
        """(episodes, empty, errors) from AgentBench's runs.jsonl: episodes whose
        last agent turn was empty, and episodes that failed rather than being
        judged (client error, or status unknown / task error)."""
        episodes = empty = errors = 0
        if not os.path.exists(runs_path):
            return 0, 0, 0
        with open(runs_path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                run = json.loads(line)
                output = run.get("output") or {}
                episodes += 1
                turns = [h for h in output.get("history") or [] if h.get("role") == "agent"]
                if turns and not str(turns[-1].get("content") or "").strip():
                    empty += 1
                if run.get("error") or output.get("status") in FAILED_STATUSES:
                    errors += 1
        return episodes, empty, errors


    def injection_rate(runs_path):
        """Share of injected episodes where the injection succeeded (lower is better)."""
        injected = succeeded = 0
        with open(runs_path) as fh:
            for line in fh:
                result = ((json.loads(line).get("output") or {}).get("result") or {})
                if (result.get("metadata") or {}).get("injection_present"):
                    injected += 1
                    succeeded += bool(result.get("injection_successful"))
        return succeeded / injected if injected else None


    def wait_for_worker(timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{CONTROLLER}/list_workers", timeout=5) as resp:
                    workers = json.load(resp)
                if AB_TASK in json.dumps(workers):
                    return
            except OSError:
                pass
            time.sleep(2)
        raise RuntimeError(f"AgentBench task worker for {AB_TASK} did not register within {timeout}s")


    def write_yaml(path, data):
        import yaml
        with open(path, "w") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)


    def main(argv=None):
        argv = argv if argv is not None else sys.argv[1:]
        if len(argv) != 1:
            print("usage: agentbench_run.py <run_dir>", file=sys.stderr)
            return 2
        run_dir = argv[0]
        record = wc.load_record(run_dir)
        base_url, model_id, _ = wc.server(record)
        limit = record.get("limit")
        out_root = os.path.join(run_dir, "agentbench")
        output_dir = os.path.join(out_root, "outputs")
        os.makedirs(out_root, exist_ok=True)

        conf_dir = "/tmp/eval-runner-agentbench"
        os.makedirs(conf_dir, exist_ok=True)
        agent_file = os.path.join(conf_dir, "agent.yaml")
        assignment_file = os.path.join(conf_dir, "assignment.yaml")
        write_yaml(agent_file, agent_config(f"{base_url}/chat/completions", model_id))
        write_yaml(assignment_file, assignment_config(agent_file, output_dir))

        env = dict(os.environ, AGENTBENCH_SAMPLE_LIMIT=str(limit or SAMPLE_LIMIT),
                   AGENTBENCH_SAMPLE_SEED=str(SAMPLE_SEED))
        server = subprocess.Popen([sys.executable, "-m", "src.start_task", "-a"], cwd=AGENTBENCH_ROOT, env=env,
                                  start_new_session=True)
        try:
            wait_for_worker()
            subprocess.run([sys.executable, "-m", "src.assigner", "--config", assignment_file],
                           cwd=AGENTBENCH_ROOT, env=env, check=True)
        finally:
            os.killpg(server.pid, signal.SIGTERM)
            server.wait(timeout=60)

        task_dir = os.path.join(output_dir, AGENT, AB_TASK)
        with open(os.path.join(task_dir, "overall.json")) as fh:
            overall = json.load(fh)["custom"]["overall"]
        runs_path = os.path.join(task_dir, "runs.jsonl")
        episodes, empty, errors = episode_counts(runs_path)
        path = wc.write_results(
            out_root, TASK,
            {"success_rate,none": overall["acc"], "passed,none": overall["pass"],
             "injection_success_rate,none": injection_rate(runs_path), "empty,none": empty,
             "errors,none": errors},
            overall["total"], TOTAL_EPISODES, limit=limit, model=model_id, base_url=base_url,
            harness="agentbench", version=VERSION, series=SERIES, max_gen_toks=MAX_TOKENS,
            runtime=wc.runtime(record),
        )
        print(f"agentbench_run: success {overall['acc']:.2f} on {overall['total']} episodes "
              f"({episodes} recorded, empty {empty}, errors {errors}) -> {path}")
        return 0


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/agentbench_run.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/agentbench_run.py | cut -d' ' -f1"
    expect: "b137117d517a84e3247850f3722e28ef0aa755447607f69938908614fd0f5520"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/agentbench_run.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-11d-repobench-run

```yaml
id: eval-runner-11d-repobench-run
title: Add the RepoBench (rebuilt) wrapper
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/repobench_run.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """RepoBench (rebuilt) for eval-runner: next-line code completion.

    The historical RepoBench numbers came from custom scripts that are lost
    (they lived only on the deleted ai-stack LXC), so this is a rebuild from
    upstream RepoBench's own code (Leolty/repobench @ e0cfd34: run.py,
    data/utils.py, eval.py, evaluation/metrics.py) on the same data, and its
    results are a new series -- not comparable with the historical numbers.

    What it does, following upstream:
      - data: tianyang/repobench_python_v1.1, settings cross_file_first,
        cross_file_random and in_file, levels 2k/4k/8k/12k/16k (upstream's
        default levels);
      - prompt: upstream construct_prompt() -- "# Repo Name", the cross-file
        snippets with "# Path" headers, then the in-file code -- with the
        cross-file part cut back line by line until the whole prompt fits in
        15800 tokens, counted by the served model's own tokenizer (llama-server
        /tokenize);
      - generation: raw text completion (/v1/completions, no chat template),
        128 new tokens, then upstream's get_first_line_not_comment();
      - metrics: exact match (whitespace-split equality) and edit similarity
        (fuzz.ratio, 0-100), per setting, then the average weighted by sample
        count (upstream eval.py). CodeBLEU is not computed (upstream's needs
        tree-sitter grammars; EM/ES are the headline numbers).

    Deviations from upstream, both to make runs reproducible and comparable
    between models: greedy decoding (temperature 0, upstream samples at 0.2),
    and a seeded sample of 100 examples per setting and level (upstream runs
    everything in a one-month date window; the historical runs also sampled
    100 per level). No date filter.

    Usage (inside the eval-runner image, via `runmeta.py exec`):
      repobench_run.py <run_dir>

    Output, under <run_dir>/repobench/: predictions_<setting>.jsonl (one line
    per answered example; a resume skips those) and results_<stamp>.json.
    """

    import json
    import os
    import random
    import re
    import sys
    import time
    import urllib.error
    import urllib.request

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import wrapper_common as wc  # noqa: E402

    TASK = "repobench_python"
    DATASET = "tianyang/repobench_python_v1.1"
    SETTINGS = ("cross_file_first", "cross_file_random", "in_file")
    LEVELS = ("2k", "4k", "8k", "12k", "16k")
    PER_LEVEL = 100
    SEED = 42
    MAX_PROMPT_TOKENS = 15800
    MAX_NEW_TOKENS = 128
    VERSION = "upstream e0cfd34 (rebuilt)"
    SERIES = "rebuilt"
    RETRIES = 3


    # --------------------------------------------------------------- upstream

    def get_first_line_not_comment(code, language="python"):
        """Upstream run.py's helper (Python branch), unchanged in behaviour."""
        code = code.lstrip("\n")
        lines = code.split("\n")
        in_multiline_comment = False
        for line in lines:
            if not line.strip():
                continue
            if not in_multiline_comment and (line.strip().startswith('"""') or line.strip().startswith("'''")):
                in_multiline_comment = True
                continue
            if in_multiline_comment and (line.strip().endswith('"""') or line.strip().endswith("'''")):
                in_multiline_comment = False
                continue
            if in_multiline_comment:
                continue
            if line.strip().startswith("#"):
                continue
            return line
        return lines[0]


    def prompt_parts(data):
        """Upstream construct_prompt()'s cross-file and in-file parts (Python)."""
        cross = f"# Repo Name: {data['repo_name']}\n"
        for snippet in data["context"]:
            cross += f"# Path: {snippet['path']}\n{snippet['snippet']}" + "\n\n"
        in_file = f"# Path: {data['file_path']}\n{data['import_statement']}\n{data['cropped_code'].rstrip()}\n"
        return cross, in_file


    def construct_prompt(data, count_tokens, max_tokens=MAX_PROMPT_TOKENS):
        """Upstream construct_prompt(). Upstream drops cross-file lines from the
        end, subtracting each line's token count, until the excess is gone;
        here the longest prefix of cross-file lines that fits is found by
        binary search over whole-prefix token counts (a handful of /tokenize
        calls instead of one per line -- the same cut up to token-boundary
        effects at line joins)."""
        cross, in_file = prompt_parts(data)
        in_tokens = count_tokens(in_file)
        if count_tokens(cross) + in_tokens > max_tokens:
            lines = cross.split("\n")
            lo, hi = 0, len(lines)  # invariant: lines[:lo] fits
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if count_tokens("\n".join(lines[:mid]) + "\n\n") + in_tokens <= max_tokens:
                    lo = mid
                else:
                    hi = mid - 1
            cross = "\n".join(lines[:lo]) + "\n\n"
        return re.sub(r"\n{4,}", "\n\n", cross + in_file)


    def exact_match(pred, gt):
        return pred.split() == gt.split()


    def edit_similarity(pred, gt):
        """fuzzywuzzy's fuzz.ratio (with python-Levenshtein): the normalised
        Indel similarity x 100, rounded -- rapidfuzz computes the same ratio."""
        from rapidfuzz import fuzz
        return int(round(fuzz.ratio(pred, gt)))


    def score(predictions):
        """{setting: (n, EM %, ES)} plus the sample-weighted averages, as upstream
        eval.py (per-setting EM rounded to 2 dp before weighting)."""
        per_setting = {}
        total = em_sum = es_sum = 0
        for setting in SETTINGS:
            rows = predictions.get(setting) or []
            if not rows:
                continue
            n = len(rows)
            em = round(100 * sum(exact_match(r["pred"], r["gt"]) for r in rows) / n, 2)
            es = round(sum(edit_similarity(r["pred"], r["gt"]) for r in rows) / n, 2)
            per_setting[setting] = (n, em, es)
            total += n
            em_sum += em * n
            es_sum += es * n
        if not total:
            return per_setting, None, None, 0
        return per_setting, round(em_sum / total, 2), round(es_sum / total, 2), total


    # ------------------------------------------------------------------ data

    def sample(rows_by_level, per_level, seed=SEED):
        """Seeded sample of up to per_level dataset indices per level, in index order."""
        rng = random.Random(seed)
        chosen = []
        for level in LEVELS:
            indices = rows_by_level.get(level, [])
            chosen += sorted(rng.sample(indices, min(per_level, len(indices))))
        return chosen


    def load_samples(per_level):
        """{setting: [(dataset index, row)]} for the seeded sample."""
        from datasets import load_dataset
        out = {}
        for setting in SETTINGS:
            data = load_dataset(DATASET, split=setting)
            by_level = {}
            for i, level in enumerate(data["level"]):
                by_level.setdefault(level, []).append(i)
            out[setting] = [(i, data[i]) for i in sample(by_level, per_level)]
        return out


    # ---------------------------------------------------------------- server

    class Server:
        def __init__(self, base_url, model_id, api_key):
            self.v1 = base_url  # .../v1
            self.root = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
            self.model = model_id
            self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            self.tokenize_ok = True

        def _post(self, url, body, timeout):
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=self.headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)

        def count_tokens(self, text):
            """llama-server /tokenize; ~4 characters per token if unavailable."""
            if self.tokenize_ok:
                try:
                    return len(self._post(f"{self.root}/tokenize", {"content": text}, 300)["tokens"])
                except (urllib.error.URLError, OSError, KeyError, ValueError):
                    self.tokenize_ok = False
                    print("repobench_run: /tokenize unavailable, estimating 4 characters per token")
            return len(text) // 4

        def complete(self, prompt):
            body = {"model": self.model, "prompt": prompt, "max_tokens": MAX_NEW_TOKENS, "temperature": 0}
            return self._post(f"{self.v1}/completions", body, 3600)["choices"][0].get("text") or ""


    def read_done(path):
        done = {}
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        done[row["idx"]] = row
        return done


    def main(argv=None):
        argv = argv if argv is not None else sys.argv[1:]
        if len(argv) != 1:
            print("usage: repobench_run.py <run_dir>", file=sys.stderr)
            return 2
        run_dir = argv[0]
        record = wc.load_record(run_dir)
        base_url, model_id, api_key = wc.server(record)
        limit = record.get("limit")
        per_level = limit or PER_LEVEL
        out_dir = os.path.join(run_dir, "repobench")
        os.makedirs(out_dir, exist_ok=True)
        server = Server(base_url, model_id, api_key)

        predictions, errors = {}, 0
        for setting, rows in load_samples(per_level).items():
            path = os.path.join(out_dir, f"predictions_{setting}.jsonl")
            done = read_done(path)
            with open(path, "a") as fh:
                for idx, data in rows:
                    if idx in done:
                        continue
                    prompt = construct_prompt(data, server.count_tokens)
                    for attempt in range(RETRIES):
                        try:
                            raw = server.complete(prompt)
                            break
                        except (urllib.error.URLError, OSError, KeyError, ValueError) as err:
                            print(f"repobench_run: {setting} {idx} attempt {attempt + 1}: {err}")
                            time.sleep(5 * (attempt + 1))
                    else:
                        errors += 1  # not recorded, so a resume retries it
                        continue
                    row = {"idx": idx, "level": data["level"], "pred": get_first_line_not_comment(raw),
                           "gt": data["next_line"], "empty": not raw.strip()}
                    fh.write(json.dumps(row) + "\n")
                    fh.flush()
                    done[idx] = row
            predictions[setting] = [done[idx] for idx, _ in rows if idx in done]

        per_setting, em, es, total = score(predictions)
        metrics = {"exact_match,weighted": em / 100 if em is not None else None,
                   "edit_similarity,weighted": es / 100 if es is not None else None,
                   "empty,none": sum(r.get("empty", False) for rows in predictions.values() for r in rows),
                   "errors,none": errors}
        for setting, (n, s_em, s_es) in per_setting.items():
            metrics[f"exact_match,{setting}"] = s_em / 100
            metrics[f"edit_similarity,{setting}"] = s_es / 100
            metrics[f"n,{setting}"] = n
        path = wc.write_results(
            out_dir, TASK, metrics, total, len(SETTINGS) * len(LEVELS) * PER_LEVEL, limit=limit, model=model_id,
            base_url=base_url, harness="repobench", version=VERSION, series=SERIES, max_gen_toks=MAX_NEW_TOKENS,
            runtime=wc.runtime(record),
        )
        print(f"repobench_run: EM {em} / ES {es} on {total} examples (errors {errors}) -> {path}")
        return 0 if not errors else 1


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/repobench_run.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/repobench_run.py | cut -d' ' -f1"
    expect: "b0d064e8b7758fd2619852844a6f3d54ff17aabd94151cb0cf538d5a614c2f08"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/repobench_run.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-11e-import-history

```yaml
id: eval-runner-11e-import-history
title: Add the historical BFCL/AgentBench importer
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/import_history.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """One-off import of historical BFCL and AgentBench results into
    eval-runner's results tree, as eval-runner results files (wrapper_common
    format), so they appear in `eval-run results`, the leaderboard and the
    Nextcloud table next to new runs -- as the GPQA/IFEval history already does.
    Not part of any image; run by the operator (docs/eval-runner/plan.md).

      probe-bfcl <site-packages dir>
          Run with framework's BFCL venv python (~/bfcl-eval/venv/bin/python,
          dir ~/bfcl-eval/venv/lib/python3.14/site-packages):
          prints JSON describing every BFCL_v3_simple score in that venv --
          accuracy, counts, empty/error answers, date, and the Ollama tag /
          endpoint from each model's handler.
      bfcl <probe.json> <results_root>
          Write one results file per probed model under
          <results_root>/_historical/bfcl-<model>/bfcl/.
      agentbench <outputs_dir> <results_root>
          For each <outputs_dir>/<stamp>/<agent>/os-std/overall.json (garuda's
          ~/eval-harnesses/AgentBench/outputs), write a results file under
          <results_root>/_historical/agentbench-<agent>-<stamp>/agentbench/.
          100-episode runs are the comparable "100 seeded" series (the seed-42
          sample every later run used); a full 800-episode run is listed as its
          own series.
    """

    import datetime
    import glob
    import json
    import os
    import re
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import wrapper_common as wc  # noqa: E402

    BFCL_VERSION = "2025.8.6.2"


    def probe_bfcl(root):
        import inspect
        os.environ.setdefault("BFCL_PROJECT_ROOT", "/tmp/bfcl-probe-root")
        from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING
        out = []
        for score in sorted(glob.glob(f"{root}/score/*/BFCL_v3_simple_score.json")):
            name = score.split("/")[-2]
            with open(score) as fh:
                head = json.loads(fh.readline())
            result = f"{root}/result/{name}/BFCL_v3_simple_result.json"
            empty = errors = 0
            if os.path.exists(result):
                with open(result) as fh:
                    for line in fh:
                        value = json.loads(line).get("result")
                        empty += value in ("", [], None)
                        errors += str(value).startswith("Error during inference")
            cfg = MODEL_CONFIG_MAPPING.get(name)
            tag = base = None
            if cfg is not None:
                src = inspect.getsource(cfg.model_handler)
                tag = getattr(cfg.model_handler, "OLLAMA_MODEL_ID", None)
                base_match = re.search(r'getenv\("\w+",\s*"([^"]+)"\)', src)
                base = base_match.group(1) if base_match else None
            out.append({"name": name, "score": head, "mtime": os.path.getmtime(score), "empty": empty,
                        "errors": errors, "tag": tag, "base_url": base})
        return out


    def bfcl_runtime(entry):
        base = entry.get("base_url") or ""
        if ":11434" in base or "-Ollama-" in entry["name"]:
            return "Ollama"
        if ":8080" in base:
            return "llama.cpp (router)"
        return "llama.cpp (router, by name)"


    def bfcl_note(name):
        effort = re.search(r"-(High|Medium|Low|None)-Ollama", name)
        return f"reasoning effort {effort.group(1).lower()}" if effort else ""


    def import_bfcl(probe, results_root):
        paths = []
        for entry in probe:
            score = entry["score"]
            model = entry["tag"] or re.sub(r"-FC$", "", entry["name"])
            full = score["total_count"] == 400
            stamp = datetime.datetime.fromtimestamp(entry["mtime"], datetime.timezone.utc)
            paths.append(wc.write_results(
                os.path.join(results_root, "_historical", f"bfcl-{entry['name']}", "bfcl"), "bfcl_simple",
                {"accuracy,none": score["accuracy"], "correct,none": score["correct_count"],
                 "empty,none": entry["empty"], "errors,none": entry["errors"]},
                score["total_count"], 400, limit=None if full else score["total_count"], model=model,
                base_url=entry.get("base_url"), harness="bfcl", version=BFCL_VERSION,
                series="v3 simple" if full else None, runtime=bfcl_runtime(entry), origin="framework",
                note=bfcl_note(entry["name"]), date=entry["mtime"], stamp=stamp.strftime("%Y-%m-%dT%H-%M-%S.000000"),
            ))
        return paths


    def import_agentbench(outputs_dir, results_root):
        import agentbench_run
        paths = []
        for overall_path in sorted(glob.glob(os.path.join(outputs_dir, "*", "*", "os-std", "overall.json"))):
            task_dir = os.path.dirname(overall_path)
            agent = os.path.basename(os.path.dirname(task_dir))
            run_stamp = os.path.basename(os.path.dirname(os.path.dirname(task_dir)))
            with open(overall_path) as fh:
                overall = json.load(fh)["custom"]["overall"]
            runs = os.path.join(task_dir, "runs.jsonl")
            _, empty, errors = agentbench_run.episode_counts(runs)
            sampled = overall["total"] == agentbench_run.SAMPLE_LIMIT
            series = agentbench_run.SERIES if sampled else f"{overall['total']} full"
            exclusion = None if sampled else (f"all {overall['total']} episodes (separate series; the ranked "
                                              f"series is the seed-42 sample of {agentbench_run.SAMPLE_LIMIT})")
            when = datetime.datetime.strptime(run_stamp, "%Y-%m-%d-%H-%M-%S")
            paths.append(wc.write_results(
                os.path.join(results_root, "_historical", f"agentbench-{agent}-{run_stamp}", "agentbench"),
                "agentbench_os_std",
                {"success_rate,none": overall["acc"], "passed,none": overall["pass"],
                 "injection_success_rate,none": agentbench_run.injection_rate(runs) if os.path.exists(runs) else None,
                 "empty,none": empty, "errors,none": errors},
                overall["total"], agentbench_run.TOTAL_EPISODES, limit=None, model=agent, base_url=None,
                harness="agentbench", version="0cfef97 (garuda)", series=series, exclusion=exclusion,
                max_gen_toks=agentbench_run.MAX_TOKENS, runtime="Ollama", origin="garuda",
                date=when.replace(tzinfo=datetime.timezone.utc).timestamp(),
                stamp=when.strftime("%Y-%m-%dT%H-%M-%S.000000"),
            ))
        return paths


    def main(argv=None):
        argv = argv if argv is not None else sys.argv[1:]
        if argv[:1] == ["probe-bfcl"] and len(argv) == 2:
            print(json.dumps(probe_bfcl(argv[1])))
            return 0
        if argv[:1] == ["bfcl"] and len(argv) == 3:
            with open(argv[1]) as fh:
                paths = import_bfcl(json.load(fh), argv[2])
        elif argv[:1] == ["agentbench"] and len(argv) == 3:
            paths = import_agentbench(argv[1], argv[2])
        else:
            print(__doc__, file=sys.stderr)
            return 2
        for path in paths:
            print(path)
        return 0


    if __name__ == "__main__":
        sys.exit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/import_history.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/import_history.py | cut -d' ' -f1"
    expect: "cc4f84ea4b8d254f8fa68a5719da1914374be450bb4eecd9703288aeafe4b762"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/import_history.py && echo OK"
    expect: "OK"
    critical: true
```

### eval-runner-11f-wrapper-selftest

```yaml
id: eval-runner-11f-wrapper-selftest
title: Add the wrapper selftest script
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/wrapper_selftest.sh with exactly this content (byte for byte, including the
  trailing newline), then run chmod 0755 on it. It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    #!/bin/sh
    # Self-test for one of eval-runner's benchmark wrappers (bfcl, agentbench,
    # repobench), run inside that wrapper's image by `eval-run selftest` (and
    # by the deploy, as a gate). Same runmeta.py start/exec path as a real run,
    # against mock_openai.py instead of Framework -- no GPU. Proves:
    #   1. a --limit run completes and writes an eval-runner results file
    #      that summarize.py accepts (numeric headline metric)
    #   2. every request matched the historical request shape for this
    #      benchmark (selftest_checks.py --harness), with the right count
    #   3. resume: re-running the same run sends zero new requests
    # Scores are meaningless (canned replies).
    #
    # Usage: wrapper_selftest.sh <harness> <limit> <expected requests>
    set -eu

    harness="$1"
    limit="$2"
    expect="$3"
    d=/opt/eval-runner
    root=/results/_selftest
    log="/tmp/selftest-${harness}-requests.jsonl"
    pids=""
    cleanup() {
      for pid in $pids; do
        kill "$pid" 2>/dev/null || true
      done
    }
    trap cleanup EXIT

    # AgentBench's agent parses "Act: answer(...)" -- answering at once makes
    # every episode one request long.
    case "$harness" in
      agentbench) reply="Think: done. Act: answer(0)" ;;
      repobench) reply="return value" ;;
      *) reply="ok" ;;
    esac

    rm -f "$log"
    export OPENAI_API_KEY=selftest
    MOCK_PORT=18082 MOCK_REQUEST_LOG="$log" MOCK_REPLY="$reply" python "$d/mock_openai.py" &
    pids="$pids $!"
    i=0
    until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=1)" 2>/dev/null; do
      i=$((i + 1))
      if [ "$i" -ge 50 ]; then
        echo "selftest FAILED: mock server did not start" >&2
        exit 1
      fi
      sleep 0.2
    done

    mkdir -p "$root"
    echo "== $harness 1. run at --limit $limit against the mock"
    run=$(python "$d/runmeta.py" start --base-url http://127.0.0.1:18082 --task "$harness" --limit "$limit" \
      --results-root "$root" --stamp "${SELFTEST_RUN:?SELFTEST_RUN must be set}" --note selftest)
    dir="$root/$run"
    python "$d/runmeta.py" exec "$dir"
    python "$d/summarize.py" --check "$dir"

    echo "== $harness 2. request shape"
    python "$d/selftest_checks.py" --harness "$harness" --requests "$log" --expect-requests "$expect" \
      --model selftest-mock

    echo "== $harness 3. resume sends no new requests"
    python "$d/runmeta.py" exec "$dir"
    python "$d/selftest_checks.py" --harness "$harness" --requests "$log" --expect-requests "$expect" \
      --model selftest-mock

    echo "$harness selftest OK"

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/wrapper_selftest.sh
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/wrapper_selftest.sh | cut -d' ' -f1"
    expect: "befb8dde8438ebb76160378443e0e5cb89b5538b7fedacc10afbc039cc4d0170"
    critical: true
  - id: shellcheck
    cmd: "shellcheck -s sh terraform/lxc/ansible/files/eval-runner/wrapper_selftest.sh"
    expect: "no output, exit 0"
    critical: true
```

### eval-runner-11g-dockerfile-bfcl

```yaml
id: eval-runner-11g-dockerfile-bfcl
title: Add the BFCL image
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/Dockerfile.bfcl with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    # eval-runner-bfcl -- BFCL (bfcl-eval 2025.8.6.2) as a thin HTTP client of
    # Framework's llama-server. Built locally on ai-services-stack by
    # deploy-ai-services-stack.yml next to eval-runner:local and started one run
    # at a time by /usr/local/bin/eval-run (`eval-run bfcl`). Its own image
    # because bfcl-eval pins numpy/tree-sitter/openai versions that lm_eval's
    # image doesn't share. See docs/eval-runner/plan.md.
    FROM python:3.12-slim

    # Same uid-1000 convention as eval-runner:local (results dir is owned by 1000).
    RUN useradd --create-home --uid 1000 app

    WORKDIR /results

    # Constrained to the exact package set of the framework venv behind every
    # historical BFCL number, so new scores stay comparable with them (109
    # packages, names and versions identical). soundfile, transformers and
    # safetensors aren't bfcl-eval dependencies but were installed in that venv
    # too -- qwen-agent, which bfcl-eval imports, fails without soundfile.
    COPY bfcl-constraints.txt /tmp/bfcl-constraints.txt
    RUN pip install --no-cache-dir --only-binary=:all: -c /tmp/bfcl-constraints.txt \
          "bfcl-eval==2025.8.6.2" soundfile transformers safetensors \
        && rm /tmp/bfcl-constraints.txt

    # The wrapper, run setup (runmeta.py exec), the shared results writer and
    # the selftest pieces. summarize/publish/selftest_checks are what the
    # selftest's checks import.
    COPY bfcl_run.py mock_openai.py publish.py runmeta.py selftest_checks.py summarize.py wrapper_common.py wrapper_selftest.sh /opt/eval-runner/
    RUN chmod 0755 /opt/eval-runner/wrapper_selftest.sh

    USER app
    ENV HOME=/home/app
    ENTRYPOINT ["python"]

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/Dockerfile.bfcl
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/Dockerfile.bfcl | cut -d' ' -f1"
    expect: "954c225e1722e23590e11ff918e6e1b4c3f9eaf86683d5e680651445969a7df1"
    critical: true
```

### eval-runner-11h-bfcl-constraints

```yaml
id: eval-runner-11h-bfcl-constraints
title: Add the BFCL pip constraints
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/bfcl-constraints.txt with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    # Exact package set of the bfcl-eval venv on framework (~/bfcl-eval/venv,
    # pip freeze 2026-10-01) that produced every historical BFCL number.
    # Used as pip constraints by Dockerfile.bfcl. That venv ran Python 3.14;
    # the image runs 3.12 (numpy 1.26.4 has no 3.14 wheels), same packages.
    aiohappyeyeballs==2.7.1
    aiohttp==3.14.3
    aiosignal==1.4.0
    annotated-doc==0.0.5
    annotated-types==0.8.0
    anthropic==0.53.0
    anyio==4.14.2
    argcomplete==3.7.0
    attrs==26.1.0
    black==26.5.1
    boto3==1.43.62
    botocore==1.43.62
    certifi==2026.7.22
    cffi==2.1.0
    charset-normalizer==3.4.9
    click==8.4.2
    cohere==5.13.3
    cryptography==50.0.0
    dashscope==1.26.5
    datamodel-code-generator==0.25.7
    distro==1.9.0
    dnspython==2.8.0
    dotenv==0.9.9
    email-validator==2.3.0
    eval_type_backport==0.4.0
    fastavro==1.12.2
    filelock==3.32.2
    frozenlist==1.8.0
    fsspec==2026.7.0
    genson==1.4.0
    google-auth==2.56.2
    google-genai==1.24.0
    h11==0.16.0
    hf-xet==1.5.2
    httpcore==1.0.9
    httpx==0.28.1
    httpx-sse==0.4.0
    huggingface_hub==1.26.0
    idna==3.18
    inflect==5.6.2
    isort==5.13.2
    Jinja2==3.1.6
    jiter==0.16.0
    jmespath==1.1.0
    json5==0.15.0
    jsonlines==4.0.0
    jsonschema==4.26.0
    jsonschema-specifications==2025.9.1
    markdown-it-py==4.2.0
    MarkupSafe==3.0.3
    mdurl==0.1.2
    mistralai==1.7.0
    mpmath==1.3.0
    multidict==6.7.1
    mypy_extensions==1.1.0
    numpy==1.26.4
    openai==2.52.1
    overrides==7.7.0
    packaging==26.2
    pandas==2.3.3
    parameterized==0.9.0
    pathlib==1.0.1
    pathspec==1.1.1
    pillow==12.3.0
    platformdirs==4.11.0
    propcache==0.5.2
    pyasn1==0.6.4
    pyasn1_modules==0.4.2
    pycparser==3.0
    pydantic==2.13.4
    pydantic_core==2.46.4
    Pygments==2.20.0
    python-dateutil==2.9.0.post0
    python-dotenv==1.2.2
    pytokens==0.4.1
    pytz==2026.3.post1
    PyYAML==6.0.3
    qwen-agent==0.0.34
    referencing==0.37.0
    regex==2026.7.19
    requests==2.34.2
    rich==15.0.0
    rpds-py==2026.6.3
    s3transfer==0.19.2
    safetensors==0.8.0
    shellingham==1.5.4
    six==1.17.0
    sniffio==1.3.1
    soundfile==0.14.0
    tabulate==0.10.0
    tenacity==8.5.0
    tiktoken==0.13.0
    tokenizers==0.22.2
    tqdm==4.70.0
    transformers==5.14.1
    tree-sitter==0.21.3
    tree-sitter-java==0.21.0
    tree-sitter-javascript==0.21.4
    typer==0.27.1
    types-requests==2.33.0.20260712
    typing_extensions==4.16.0
    typing-inspection==0.4.2
    tzdata==2026.3
    urllib3==2.7.0
    websocket-client==1.9.0
    websockets==15.0.1
    writer-sdk==3.0.0
    yarl==1.24.5

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/bfcl-constraints.txt
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/bfcl-constraints.txt | cut -d' ' -f1"
    expect: "bc9b8f8bc3e17b2f4066870e1bd048022082bb0b7b03f99f14cf52fec8604247"
    critical: true
```

### eval-runner-11i-dockerfile-agentbench

```yaml
id: eval-runner-11i-dockerfile-agentbench
title: Add the AgentBench image
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/Dockerfile.agentbench with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    # eval-runner-agentbench -- AgentBench os-std (Eugleo/agent-bench, pinned
    # commit, plus agentbench.patch) as an HTTP client of Framework's
    # llama-server. Built on ai-services-stack by deploy-ai-services-stack.yml
    # and started one run at a time by `eval-run agentbench`, which mounts the
    # CT's Docker socket: AgentBench's task worker starts one throwaway sandbox
    # container (local-os/default, Dockerfile.agentbench-sandbox) per episode,
    # with networking disabled. See docs/eval-runner/plan.md.
    FROM python:3.11-slim

    RUN apt-get update \
        && apt-get install -y --no-install-recommends patch \
        && rm -rf /var/lib/apt/lists/* \
        && useradd --create-home --uid 1000 app

    # The commit every historical AgentBench number ran from (garuda's
    # ~/eval-harnesses/AgentBench), checksum-verified.
    ARG AGENTBENCH_COMMIT=0cfef9785eedf4de13a7a994b6df486f56a38515
    ARG AGENTBENCH_SHA256=7e5ea8a517a3dcfe98a1c78037570b11954d65ef2ee5edb7db6038f48d962806
    COPY agentbench.patch /tmp/agentbench.patch
    RUN python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/Eugleo/agent-bench/archive/${AGENTBENCH_COMMIT}.tar.gz', '/tmp/agentbench.tar.gz')" \
        && echo "${AGENTBENCH_SHA256}  /tmp/agentbench.tar.gz" | sha256sum -c - \
        && mkdir /opt/agentbench \
        && tar -xzf /tmp/agentbench.tar.gz -C /opt/agentbench --strip-components=1 \
        && patch -d /opt/agentbench -p1 < /tmp/agentbench.patch \
        && rm /tmp/agentbench.tar.gz /tmp/agentbench.patch

    # AgentBench's requirements.txt minus FastChat/accelerate/transformers (the
    # HTTP agent doesn't need them, and they pull in torch), constrained to the
    # historical venv's versions.
    COPY agentbench-constraints.txt /tmp/agentbench-constraints.txt
    RUN grep -v -E '^(fschat|accelerate|transformers)' /opt/agentbench/requirements.txt > /tmp/requirements.txt \
        && pip install --no-cache-dir --only-binary=:all: -c /tmp/agentbench-constraints.txt -r /tmp/requirements.txt \
        && rm /tmp/requirements.txt /tmp/agentbench-constraints.txt

    WORKDIR /results
    COPY agentbench_run.py mock_openai.py publish.py runmeta.py selftest_checks.py summarize.py wrapper_common.py wrapper_selftest.sh /opt/eval-runner/
    RUN chmod 0755 /opt/eval-runner/wrapper_selftest.sh

    USER app
    ENV HOME=/home/app
    ENTRYPOINT ["python"]

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/Dockerfile.agentbench
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/Dockerfile.agentbench | cut -d' ' -f1"
    expect: "cd4c325ceb9135ee2532d1b0332cf5c37da27f19002dc2a01fd10a22c55e8f9b"
    critical: true
```

### eval-runner-11j-agentbench-patch

```yaml
id: eval-runner-11j-agentbench-patch
title: Add the AgentBench patch
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/agentbench.patch with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    diff -ru a/src/client/agents/http_agent.py b/src/client/agents/http_agent.py
    --- a/src/client/agents/http_agent.py
    +++ b/src/client/agents/http_agent.py
    @@ -1,4 +1,5 @@
     import contextlib
    +import os
     import time
     import warnings

    @@ -175,7 +176,10 @@
             super().__init__(**kwargs)
             self.url = url
             self.proxies = proxies or {}
    -        self.headers = headers or {}
    +        # eval-runner: header values may reference environment variables
    +        # ("Bearer ${OPENAI_API_KEY}"), so no API key is written into
    +        # config files or the run's output config.yaml.
    +        self.headers = {k: os.path.expandvars(str(v)) for k, v in (headers or {}).items()}
             self.body = body or {}
             self.return_format = return_format
             self.prompter = Prompter.get_prompter(prompter)
    @@ -192,7 +196,11 @@
                     body.update(self._handle_history(history))
                     with no_ssl_verification():
                         resp = requests.post(
    -                        self.url, json=body, headers=self.headers, proxies=self.proxies, timeout=120
    +                        # eval-runner: 120s timed out slow models mid-answer
    +                        # (3072 tokens at ~17 tok/s is ~180s); the timeout
    +                        # doesn't change answers, only spurious failures.
    +                        self.url, json=body, headers=self.headers, proxies=self.proxies,
    +                        timeout=int(os.environ.get("AGENTBENCH_HTTP_TIMEOUT", "3600")),
                         )
                     # print(resp.status_code, resp.text)
                     if resp.status_code != 200:
    diff -ru a/src/client/agents/__init__.py b/src/client/agents/__init__.py
    --- a/src/client/agents/__init__.py
    +++ b/src/client/agents/__init__.py
    @@ -1,2 +1,6 @@
    -from .fastchat_client import FastChatAgent
    +# eval-runner: FastChat pulls in torch/transformers; only HTTPAgent is used.
    +try:
    +    from .fastchat_client import FastChatAgent
    +except ImportError:
    +    FastChatAgent = None
     from .http_agent import HTTPAgent
    diff -ru a/src/server/tasks/os_interaction/task.py b/src/server/tasks/os_interaction/task.py
    --- a/src/server/tasks/os_interaction/task.py
    +++ b/src/server/tasks/os_interaction/task.py
    @@ -31,6 +31,11 @@
                 tty=True,
                 stdin_open=True,
                 remove=True,
    +            # eval-runner: the model's shell commands run here, so no
    +            # network. Every package the task inits would apt-get is baked
    +            # into the local-os/default image instead (their apt-get then
    +            # fails harmlessly -- init exit codes are ignored).
    +            network_disabled=True,
                 # name="os-pipeline-ubuntu",
                 labels={"created_by": "os-pipeline"},
             )
    @@ -374,7 +379,32 @@
             }

         def get_indices(self) -> List[Any]:
    -        return list(self.problem_configs.keys())
    +        # NOTE: patched 2026-08-05 -- AgentBench's os-std has no built-in
    +        # sample-count limit (800 episodes total, ~90-100s each at
    +        # concurrency=1 == ~20+ hours for a single model). Set
    +        # AGENTBENCH_SAMPLE_LIMIT to cap it for controlled/subsampled runs.
    +        #
    +        # NOTE: patched 2026-08-06 -- neither a plain prefix slice
    +        # (indices[:N]) nor a fixed stride (indices[::k]) is representative:
    +        # the 800 tasks are 14 base task_ids x ~70 injection-variant copies
    +        # each, and BOTH the first-100 prefix AND a stride-8 sample landed
    +        # on 0/100 pass by coincidence of how copies are ordered, against a
    +        # model that scores 27% over the full 800. Set AGENTBENCH_SAMPLE_SEED
    +        # (any int) alongside AGENTBENCH_SAMPLE_LIMIT to take a genuine
    +        # random sample instead -- robust to whatever periodic structure
    +        # the underlying ordering has. Falls back to a plain prefix slice
    +        # if seed is unset, preserving old behavior.
    +        import os
    +        import random
    +        indices = list(self.problem_configs.keys())
    +        limit = os.getenv("AGENTBENCH_SAMPLE_LIMIT")
    +        seed = os.getenv("AGENTBENCH_SAMPLE_SEED")
    +        if limit and seed:
    +            rng = random.Random(int(seed))
    +            indices = rng.sample(indices, min(int(limit), len(indices)))
    +        elif limit:
    +            indices = indices[: int(limit)]
    +        return indices

         def extract_action(self, raw: str):
             think_pattern = r"Think:\s*(.+)"

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/agentbench.patch
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/agentbench.patch | cut -d' ' -f1"
    expect: "f8718d60ac84306fca23dfa4bdd314054ac6539eb6e2b1713bd6ab4a6020124a"
    critical: true
```

### eval-runner-11k-agentbench-constraints

```yaml
id: eval-runner-11k-agentbench-constraints
title: Add the AgentBench pip constraints
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/agentbench-constraints.txt with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    # Package versions of the AgentBench venv on garuda (~/eval-harnesses/
    # AgentBench/.venv, Python 3.9, pip freeze 2026-10-01) behind the historical
    # AgentBench numbers. Pip constraints for Dockerfile.agentbench, which
    # installs AgentBench's requirements.txt minus fschat/accelerate/
    # transformers (FastChat's agent client isn't used, so neither is torch).
    aiohttp==3.8.6
    aiosignal==1.4.0
    anthropic==0.4.1
    anyio==3.7.1
    async-timeout==4.0.3
    attrs==26.1.0
    certifi==2026.7.22
    charset-normalizer==3.4.9
    click==8.1.8
    distro==1.9.0
    docker==6.1.2
    exceptiongroup==1.3.1
    fastapi==0.101.1
    filelock==3.19.1
    frozenlist==1.8.0
    fsspec==2025.10.0
    h11==0.16.0
    httpcore==1.0.9
    httpx==0.28.1
    huggingface-hub==0.17.3
    idna==3.18
    importlib_metadata==8.7.1
    isodate==0.7.2
    Jinja2==3.1.6
    jsonlines==3.1.0
    latex2mathml==3.78.1
    markdown2==2.5.5
    markdown-it-py==3.0.0
    MarkupSafe==3.0.3
    mdurl==0.1.2
    mpmath==1.3.0
    multidict==6.7.1
    mysql-connector-python==8.0.33
    networkx==2.8.8
    nh3==0.3.6
    numpy==1.23.5
    packaging==26.3
    prompt_toolkit==3.0.52
    propcache==0.4.1
    protobuf==3.20.3
    psutil==7.2.2
    pydantic==1.10.26
    Pygments==2.20.0
    pyparsing==3.3.2
    PyYAML==6.0.3
    rdflib==7.6.0
    regex==2026.1.15
    requests==2.28.2
    rich==15.0.0
    shortuuid==1.0.13
    six==1.17.0
    sniffio==1.3.1
    SPARQLWrapper==2.0.0
    starlette==0.27.0
    svgwrite==1.4.3
    sympy==1.14.0
    tiktoken==0.13.0
    tokenizers==0.14.1
    tqdm==4.65.2
    typing_extensions==4.16.0
    urllib3==1.26.20
    uvicorn==0.22.0
    wavedrom==2.0.3.post3
    wcwidth==0.8.2
    websocket-client==1.9.0
    yarl==1.22.0
    zipp==3.23.1

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/agentbench-constraints.txt
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/agentbench-constraints.txt | cut -d' ' -f1"
    expect: "667126fa8350d01a07eee9b494f4c2f70fb24cbb2e97420fc4b97f18690ef78b"
    critical: true
```

### eval-runner-11l-dockerfile-sandbox

```yaml
id: eval-runner-11l-dockerfile-sandbox
title: Add the AgentBench sandbox image
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/Dockerfile.agentbench-sandbox with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    # local-os/default -- the sandbox each AgentBench os-std episode runs in
    # (one throwaway container per episode, networking disabled, started by
    # eval-runner-agentbench's task worker). Same as AgentBench's own
    # data/os_interaction/res/dockerfiles/default, but:
    #   - pinned to ubuntu:26.04, the release the historical images were built
    #     from (August 2026, `FROM ubuntu` = 26.04 then);
    #   - with every package the os-std task inits apt-get at episode start
    #     pre-installed (netcat-openbsd for "netcat", libssl-dev, wamerican,
    #     and install_nettools.sh's net-tools/iproute2/lsof). With networking
    #     disabled those apt-gets fail -- harmlessly, AgentBench ignores init
    #     exit codes -- and the tools are already there, as they were when the
    #     historical runs fetched them over the network.
    ARG UBUNTU_IMAGE=ubuntu:26.04
    FROM ${UBUNTU_IMAGE}
    RUN apt-get update \
        && apt-get install -y python3 python3-pip git vim curl wget unzip zip tree \
           netcat-openbsd net-tools iproute2 lsof libssl-dev wamerican
    CMD ["bash"]

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/Dockerfile.agentbench-sandbox
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/Dockerfile.agentbench-sandbox | cut -d' ' -f1"
    expect: "e5316dbfd2750ce69bef4f8f155fb4c31468b04238d581b8f352adbe35b165fb"
    critical: true
```

### eval-runner-11m-test-wrappers

```yaml
id: eval-runner-11m-test-wrappers
title: Add wrapper unit tests
depends_on:
  - eval-runner-11a-wrapper-common
  - eval-runner-11b-bfcl-run
  - eval-runner-11c-agentbench-run
  - eval-runner-11d-repobench-run
  - eval-runner-11e-import-history
  - eval-runner-06j-test-publish

change: |
  Create terraform/lxc/ansible/files/eval-runner/test_wrappers.py with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    """Unit tests for the benchmark wrappers' own logic (bfcl_run.py,
    agentbench_run.py, repobench_run.py, wrapper_common.py) and how their
    results flow into summarize/publish. The benchmarks themselves run only in
    their images (eval-run selftest). Run with:
    python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
    """

    import json
    import os
    import tempfile
    import unittest

    import agentbench_run
    import bfcl_run
    import publish
    import repobench_run
    import summarize
    import wrapper_common as wc

    try:
        import rapidfuzz  # noqa: F401
    except ImportError:  # in the image; locally: pip install rapidfuzz==3.14.6 in a venv
        rapidfuzz = None


    def write_jsonl(path, rows):
        with open(path, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")


    class BfclTest(unittest.TestCase):
        def test_pilot_ids_are_evenly_spaced(self):
            self.assertEqual(bfcl_run.pilot_ids(20)[:3], ["simple_0", "simple_20", "simple_40"])
            self.assertEqual(len(bfcl_run.pilot_ids(40)), 40)
            self.assertEqual(bfcl_run.pilot_ids(2), ["simple_0", "simple_200"])

        def test_errored_entries_are_dropped_for_retry(self):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "r.json")
                write_jsonl(path, [{"id": "simple_0", "result": [{"f": "{}"}]},
                                   {"id": "simple_1", "result": "Error during inference: timeout"}])
                self.assertEqual(bfcl_run.drop_errored(path), 1)
                with open(path) as fh:
                    self.assertEqual([json.loads(line)["id"] for line in fh], ["simple_0"])
                self.assertEqual(bfcl_run.drop_errored(os.path.join(tmp, "missing.json")), 0)

        def test_response_counts(self):
            entries = [{"result": []}, {"result": ""}, {"result": "Error during inference: x"}, {"result": [{"f": "{}"}]}]
            self.assertEqual(bfcl_run.response_counts(entries), (2, 1))


    class AgentBenchTest(unittest.TestCase):
        def test_agent_config_matches_history_without_a_secret(self):
            conf = agentbench_run.agent_config("http://f:8080/v1/chat/completions", "glm")["eval-runner"]["parameters"]
            self.assertEqual(conf["body"], {"model": "glm", "temperature": 0, "max_tokens": 3072})
            self.assertEqual(conf["headers"]["Authorization"], "Bearer ${OPENAI_API_KEY}")
            self.assertEqual(conf["prompter"], {"name": "role_content_dict", "args": {"agent_role": "assistant"}})
            self.assertEqual(conf["return_format"], "{response[choices][0][message][content]}")

        def test_assignment_points_at_output_and_controller(self):
            conf = agentbench_run.assignment_config("/tmp/a.yaml", "/results/r/agentbench/outputs")
            self.assertEqual(conf["output"], "/results/r/agentbench/outputs")
            self.assertEqual(conf["assignments"], [{"agent": ["eval-runner"], "task": ["os-std"]}])
            self.assertTrue(conf["definition"]["task"]["import"].startswith("/opt/agentbench/"))

        def test_episode_counts_and_injection_rate(self):
            runs = [
                {"error": None, "output": {"status": "completed", "history": [{"role": "agent", "content": "Act: finish"}],
                                           "result": {"metadata": {"injection_present": True},
                                                      "injection_successful": True}}},
                {"error": None, "output": {"status": "agent invalid action", "history": [{"role": "agent", "content": ""}],
                                           "result": {"metadata": {"injection_present": True},
                                                      "injection_successful": False}}},
                {"error": "boom", "output": {"status": "unknown", "history": [], "result": {"metadata": {}}}},
            ]
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "runs.jsonl")
                write_jsonl(path, runs)
                self.assertEqual(agentbench_run.episode_counts(path), (3, 1, 1))
                self.assertEqual(agentbench_run.injection_rate(path), 0.5)
                self.assertEqual(agentbench_run.episode_counts(os.path.join(tmp, "none")), (0, 0, 0))


    class RepoBenchTest(unittest.TestCase):
        def test_first_line_not_comment(self):
            f = repobench_run.get_first_line_not_comment
            self.assertEqual(f("\n# comment\n    x = 1\ny = 2"), "    x = 1")
            self.assertEqual(f('"""doc\nmore"""\nreturn a'), "return a")
            self.assertEqual(f("# only\n# comments"), "# only")

        def test_prompt_matches_upstream_when_it_fits(self):
            data = {"repo_name": "r", "context": [{"path": "a.py", "snippet": "def a(): pass"}],
                    "file_path": "b.py", "import_statement": "import a", "cropped_code": "x = a()\n\n"}
            prompt = repobench_run.construct_prompt(data, lambda text: 0)
            self.assertEqual(prompt, "# Repo Name: r\n# Path: a.py\ndef a(): pass\n\n# Path: b.py\nimport a\nx = a()\n")

        def test_cross_file_part_is_cut_to_fit(self):
            snippets = [{"path": f"m{i}.py", "snippet": "y" * 40} for i in range(10)]
            data = {"repo_name": "r", "context": snippets, "file_path": "b.py", "import_statement": "",
                    "cropped_code": "z"}
            prompt = repobench_run.construct_prompt(data, len, max_tokens=200)  # 1 "token" per character
            self.assertLessEqual(len(prompt), 200)
            self.assertTrue(prompt.startswith("# Repo Name: r\n# Path: m0.py"))
            self.assertTrue(prompt.endswith("# Path: b.py\n\nz\n"))

        def test_sample_is_seeded_and_capped(self):
            by_level = {"2k": list(range(50)), "4k": list(range(100, 103))}
            first = repobench_run.sample(by_level, 5)
            self.assertEqual(first, repobench_run.sample(by_level, 5))
            self.assertEqual(len(first), 8)  # 5 from 2k, all 3 from 4k
            self.assertEqual(first[-3:], [100, 101, 102])

        @unittest.skipUnless(rapidfuzz, "rapidfuzz not installed")
        def test_scores_are_weighted_by_sample_count(self):
            preds = {"cross_file_first": [{"pred": "a = 1", "gt": "a  =  1"}, {"pred": "b", "gt": "c"}],
                     "in_file": [{"pred": "x", "gt": "x"}] * 2}
            per, em, es, total = repobench_run.score(preds)
            self.assertEqual(per["cross_file_first"][:2], (2, 50.0))
            self.assertEqual(per["in_file"], (2, 100.0, 100.0))
            self.assertEqual((em, total), (75.0, 4))
            self.assertEqual(repobench_run.edit_similarity("abc", "abd"), 67)


    class ImportHistoryTest(unittest.TestCase):
        def test_bfcl_probe_becomes_comparable_rows(self):
            import import_history
            probe = [
                {"name": "Gemma4-26B-Ollama-FC", "score": {"accuracy": 0.94, "correct_count": 376, "total_count": 400},
                 "mtime": 1785888000, "empty": 0, "errors": 0, "tag": "gemma4:26b", "base_url": "http://localhost:11434/v1"},
                {"name": "Qwen3.8-27B-UDQ4KXL-High-Ollama-FC",
                 "score": {"accuracy": 0.925, "correct_count": 370, "total_count": 400},
                 "mtime": 1789000000, "empty": 1, "errors": 0, "tag": "qwen3.8-27b-q4kxl-ctx32k", "base_url": None},
                {"name": "Laguna-S-2-1-UD-Q4-K-M-FC", "score": {"accuracy": 0.755, "correct_count": 302, "total_count": 400},
                 "mtime": 1785888000, "empty": 34, "errors": 0, "tag": None, "base_url": "http://localhost:8080/v1"},
            ]
            with tempfile.TemporaryDirectory() as root:
                import_history.import_bfcl(probe, root)
                _, rows = publish.build_files(publish.collect(root), None, "NOW")
            by_model = {r["Model"]: r for r in rows}
            self.assertEqual(set(by_model), {"gemma4:26b", "qwen3.8-27b-q4kxl-ctx32k", "Laguna-S-2-1-UD-Q4-K-M"})
            gemma = by_model["gemma4:26b"]
            self.assertEqual((gemma["Score %"], gemma["Comparable"], gemma["Runtime"], gemma["Source"]),
                             (94.0, "yes", "Ollama", "historical (framework)"))
            self.assertEqual(by_model["qwen3.8-27b-q4kxl-ctx32k"]["Note"], "reasoning effort high")
            self.assertEqual(by_model["Laguna-S-2-1-UD-Q4-K-M"]["Runtime"], "llama.cpp (router)")
            self.assertEqual(by_model["Laguna-S-2-1-UD-Q4-K-M"]["Empty answers"], 34)

        def test_agentbench_sampled_and_full_runs(self):
            import import_history
            with tempfile.TemporaryDirectory() as tmp:
                outputs, root = os.path.join(tmp, "outputs"), os.path.join(tmp, "results")
                for stamp, agent, total, passed in (("2026-08-06-08-20-09", "qwen36-35b", 100, 22),
                                                    ("2026-08-05-21-14-17", "qwen3-coder-30b", 800, 216)):
                    task_dir = os.path.join(outputs, stamp, agent, "os-std")
                    os.makedirs(task_dir)
                    with open(os.path.join(task_dir, "overall.json"), "w") as fh:
                        json.dump({"total": total, "custom": {"overall": {"total": total, "pass": passed,
                                                                          "acc": passed / total}}}, fh)
                import_history.import_agentbench(outputs, root)
                _, rows = publish.build_files(publish.collect(root), None, "NOW")
            by_model = {r["Model"]: r for r in rows}
            self.assertEqual((by_model["qwen36-35b"]["Score %"], by_model["qwen36-35b"]["Comparable"]), (22.0, "yes"))
            coder = by_model["qwen3-coder-30b"]
            self.assertEqual((coder["Comparable"], coder["Series"]), ("no", "800 full"))
            self.assertIn("separate series", coder["Why not comparable"])
            self.assertEqual(coder["Source"], "historical (garuda)")


    class ResultsFlowTest(unittest.TestCase):
        """A wrapper's results file goes through summarize and publish like lm_eval's."""

        def _write(self, root, task, metrics, limit=None, series="v3 simple", exclusion=None):
            run_dir = os.path.join(root, "glm-bfcl-S")
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "run.json"), "w") as fh:
                json.dump({"run": "glm-bfcl-S", "tasks": [task], "created_utc": "20261002T000000Z", "note": "",
                           "server": {"model_id": "glm", "props": {"build_info": "b1", "model_path": "/m/g.gguf"}}}, fh)
            wc.write_results(os.path.join(run_dir, "bfcl"), task, metrics, 400, 400, limit=limit, model="glm",
                             base_url="http://f:8080/v1", harness="bfcl", version="2025.8.6.2", series=series,
                             exclusion=exclusion, runtime="llama.cpp b1", stamp="2026-10-02T00-00-00.000000")
            return run_dir

        def test_comparable_wrapper_result_is_ranked(self):
            with tempfile.TemporaryDirectory() as root:
                run_dir = self._write(root, "bfcl_simple", {"accuracy,none": 0.9425, "empty,none": 3, "errors,none": 1})
                line, ok = summarize.describe(run_dir, check=True)
                self.assertTrue(ok)
                self.assertIn("BFCL simple 94.25%", line)
                self.assertIn("empty 3, errors 1", line)
                files, rows = publish.build_files(publish.collect(root), None, "NOW")
            row = rows[0]
            self.assertEqual((row["Task"], row["Score %"], row["Alt score %"], row["Metrics"]),
                             ("BFCL simple", 94.25, None, "accuracy"))
            self.assertEqual((row["Comparable"], row["Series"], row["Runtime"]), ("yes", "v3 simple", "llama.cpp b1"))
            self.assertEqual(row["Empty answers"], 3)
            self.assertIn("| 1 | glm | 94.25% | – |", files["leaderboard.md"].decode())

        def test_pilot_wrapper_result_is_excluded(self):
            with tempfile.TemporaryDirectory() as root:
                self._write(root, "bfcl_simple", {"accuracy,none": 0.5, "empty,none": 0}, limit=40)
                _, rows = publish.build_files(publish.collect(root), None, "NOW")
            self.assertEqual((rows[0]["Comparable"], rows[0]["Why not comparable"]), ("no", "pilot (limit 40)"))
            self.assertEqual(rows[0]["Series"], "")

        def test_every_wrapper_task_has_labels_series_and_a_view(self):
            view_tasks = {task for _, _, task, _ in publish.VIEWS}
            for task in summarize.HEADLINE:
                self.assertIn(task, publish.TASK_LABELS)
                self.assertIn(task, summarize.STANDARD_SERIES)
                self.assertIn(publish.TASK_LABELS[task][0], view_tasks)
            self.assertEqual(summarize.STANDARD_SERIES["bfcl_simple"], bfcl_run.SERIES)
            self.assertEqual(summarize.STANDARD_SERIES["agentbench_os_std"], agentbench_run.SERIES)
            self.assertEqual(summarize.STANDARD_SERIES["repobench_python"], repobench_run.SERIES)


    if __name__ == "__main__":
        unittest.main()

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/test_wrappers.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/test_wrappers.py | cut -d' ' -f1"
    expect: "7214c11260b2227ef676e9ff5eb623def560cf28f16479738f5600e52b792193"
    critical: true
  - id: unit-tests
    cmd: "python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner/ -p 'test_*.py' 2>&1 | tail -1"
    expect: "OK, or OK (skipped=N) where openpyxl/rapidfuzz are not installed"
    critical: true
```

### eval-runner-08-findings

```yaml
id: eval-runner-08-findings
title: Add the curated findings document
depends_on: []

change: |
  Create docs/eval-runner/findings.md with exactly this content (byte for byte, including the
  trailing newline). It is shown indented by 4 spaces below;
  the file itself has no leading indentation:

    # Model evaluation findings

    Hand-written analysis to read alongside the generated `leaderboard.xlsx`
    (or `leaderboard.md`) and the Nextcloud Tables table **Model
    evaluations**. The numbers in those
    come from `eval-run publish`; this file explains how far to trust them.
    The canonical copy is `docs/eval-runner/findings.md` in the repo. The
    eval-runner image ships it and `eval-run publish` mirrors it into
    Nextcloud.

    Last updated: 2026-10-01 (32k series; BFCL/AgentBench/RepoBench added).

    ## How results are produced

    - **Harness.** lm-evaluation-harness 0.4.12, `local-chat-completions`
      against an OpenAI-compatible server, with `--apply_chat_template`.
      - GPQA: `gpqa_diamond_cot_zeroshot`, 198 questions.
      - IFEval: 541 prompts.
    - **Decoding.** Greedy: both task configs pin `temperature: 0`, overriding
      any server default. The seed is 1234.
    - **Token budget.** `max_gen_toks` is 8192 per answer, the same for every
      historical result. Runs at a larger budget (`--max-gen-toks 32768`)
      form a separate **32k series**, ranked only among themselves.
    - **Historical results.** These were run on framework through Ollama in
      August–September 2026. New results come from `eval-runner` on
      `ai-services-stack`, against whatever llama-server serves.
    - **Comparable** means a full run (no `--limit`) at the 8192 budget, as
      recorded in lm_eval's own results file. Pilots and runs without the cap
      are listed but not ranked.

    ## Findings

    ### 1. Under 8192 tokens, GPQA mostly measures whether the model finishes

    Empty GPQA answers in the comparable historical runs:

    | Model | GPQA flex | Empty answers | No parseable letter |
    |---|---|---|---|
    | Qwen3.6-35B-A3B (Q4_K_M) | 57.07% | 49 / 198 (24.7%) | 54 |
    | Gemma4-26B (Q4) | 43.94% | 91 / 198 (46.0%) | 95 |
    | Qwen3.8-27B (Q4_K_M) | 43.43% | 105 / 198 (53.0%) | 107 |
    | Gemma4-26B-A4B-QAT (Q4_0) | 27.27% | 134 / 198 (67.7%) | 137 |
    | Laguna S2.1 (Q4_K_M) | 24.24% | 114 / 198 (57.6%) | 127 |

    An empty answer means the response had no answer content: the reasoning
    used up the budget first. This matches the earlier observation that many
    Qwen3.8-27B responses stopped at exactly 8192 tokens.

    **Implications:**
    - The GPQA ranking is largely a ranking of reasoning *length* against a
      fixed budget, not of correctness. A model that thinks less can outscore
      a more accurate one that thinks more.
    - Don't compute "accuracy on the questions it answered" to correct for
      this. The questions a model finishes inside the budget are likely the
      easier ones, and they differ per model. That figure came out at an
      implausible 94.5% for Qwen3.8-27B, so it isn't comparable either.
    - The honest fix is a larger budget. Results at a different budget
      aren't comparable with history, so they are kept as a separate,
      labelled series: the 32k series (decided 2026-10-01). No 32k results
      exist yet.

    ### 2. IFEval is far less affected

    IFEval empty answers run from 0% to 4.8% in the same runs, because its
    prompts need short outputs. The IFEval ranking is the more trustworthy of
    the two:
    - Gemma4-26B 92.98%
    - Qwen3.6-35B 90.39%
    - A4B-QAT 89.83%
    - Qwen3.8-27B 89.46%
    - Qwen3-Coder-30B 81.33%
    - Laguna S2.1 75.42%

    ### 3. GPQA "strict-match" is always 0% and carries no information

    The task's strict filter only accepts the literal text `The answer is
    (X)`. The zero-shot prompt never asks for that format, and models write
    things like `The correct answer is **(C)**`. So strict-match scores 0.00%
    for every model.

    Use **flexible-extract** (the last `(A)`–`(D)` in the response) as the
    GPQA score. The table shows strict-match only for completeness.

    ### 4. Excluded historical runs, and why

    - **Bug 6 (no token cap):** `lm_eval`'s client sent `max_tokens: 256`
      unless `max_gen_toks` was passed.
      - Qwen3.6-35B's first runs scored GPQA 0.00% and IFEval 17.74%
        (redo: 57.07% / 90.39%).
      - Qwen3-Coder-30B's first run (GPQA 11.62%, IFEval 79.11%) also used a
        `ctx163k` Ollama tag, since found to degenerate on dense content.
    - **Pilots** (`--limit 40`), for example Gemma4-26B's: these were for
      checking the infrastructure, not for scoring.

    The automatic rule (full run with `max_gen_toks=8192`) selects exactly the
    set the eval-battery doc treats as valid.

    ### 5. BFCL, AgentBench and RepoBench history

    - **BFCL simple (18 imported results)** clusters at 90-96% for every
      usable model, so it separates broken tool calling more than it ranks
      good models. Two outliers are runtime problems, not capability:
      - Laguna S2.1 on the llama.cpp router scored 75.50% with 34 empty
        answers, against 92.75% on Ollama (the reason Laguna stays on
        Ollama).
      - Llama4-Scout scored 16.25%.
      The Qwen3.8-27B reasoning-effort variants (none/low/medium/high) all
      land within 92.5-93.75%, so effort doesn't matter on single calls.
    - **AgentBench os-std:** only two historical outputs survive.
      - Qwen3.6-35B: 22% on the seed-42 sample of 100 (comparable).
      - Qwen3-Coder-30B: 27% over all 800 episodes (its own series).
      - The other historical numbers are known only from
        `docs/framework/eval-battery-phase2-plan.md` and can't be imported:
        Gemma4-26B 47%, the A4B-QAT 42%, Qwen3-Coder-Next 36% and
        Laguna-Heretic 38%.
      - Sampling noise is large: an identical-config Qwen3.6-35B repeat
        swung 30% to 10% at n=10, which is why the floor is n=100.
      - os-std is the prompt-injection variant, so eval-runner also records
        `injection_success_rate` (lower is better) in each results file.
    - **RepoBench:** the six historical results (for example Qwen3.6-35B EM
      17.33% / ES 41.0%) came from lost scripts that sent chat prompts with
      an "output only code" instruction, and scored a compliance rate as
      well. The rebuilt series uses upstream's raw-completion method, so
      expect different absolute numbers. It ranks only against itself.

    ## Open questions

    - **Budget:** how much do the 32k-series scores differ from the 8k ones
      for the same model? The first pair of runs (8k and 32k for one
      reasoning model) will show whether the 8k ranking holds up.
    - **RepoBench calibration:** re-running one historical RepoBench model
      in the rebuilt series would show how far the two methods differ. That
      needs the same model served by llama.cpp.
    - **Comparability with history:** GLM-5.3-Flash runs on llama.cpp with
      server-side `reasoning_effort=high`, while the historical runs used
      Ollama defaults. A runtime or reasoning-mode difference is recorded per
      run (Runtime and Note columns), but it still limits how directly the
      numbers compare.

scope:
  allowed_paths:
    - docs/eval-runner/findings.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum docs/eval-runner/findings.md | cut -d' ' -f1"
    expect: "efcf5a5248366653ceffd1a035dd7810a3463e66b86a509327d85589dcc052ac"
    critical: true
```

### eval-runner-04-playbook-play

```yaml
id: eval-runner-04-playbook-play
title: Append the eval-runner play to deploy-ai-services-stack.yml
depends_on:
  - eval-runner-02-dockerfile
  - eval-runner-03-eval-run-script
  - eval-runner-06a-mock-server
  - eval-runner-06b-selftest-script
  - eval-runner-06c-summarize
  - eval-runner-06d-runmeta
  - eval-runner-06e-selftest-checks
  - eval-runner-06h-publish
  - eval-runner-06i-mock-nextcloud
  - eval-runner-08-findings
  - eval-runner-11a-wrapper-common
  - eval-runner-11b-bfcl-run
  - eval-runner-11c-agentbench-run
  - eval-runner-11d-repobench-run
  - eval-runner-11f-wrapper-selftest
  - eval-runner-11g-dockerfile-bfcl
  - eval-runner-11h-bfcl-constraints
  - eval-runner-11i-dockerfile-agentbench
  - eval-runner-11j-agentbench-patch
  - eval-runner-11k-agentbench-constraints
  - eval-runner-11l-dockerfile-sandbox

change: |
  Append to the end of terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml
  one blank line followed by exactly this content (a new, separate play;
  do not edit or move any existing line in the file). It is shown
  indented by 4 spaces below; in the playbook the play starts at
  column 0 ("- name:"):

    - name: Install eval-runner (GPQA/IFEval/BFCL/AgentBench/RepoBench against Framework's llama-server)
      hosts: all
      become: true
      gather_facts: false
      vars:
        repo_root: "{{ (playbook_dir + '/../../../..') | realpath }}"
        eval_runner_source_dir: "{{ repo_root }}/terraform/lxc/ansible/files/eval-runner"
        eval_runner_build_dir: /opt/eval-runner
        eval_runner_framework_host: "{{ lookup('env', 'LAB_FQDN_FRAMEWORK') | default('framework.gibbsgreatly.xyz', true) }}"
        eval_runner_llm_api_key: "{{ lookup('env', 'LLM_GPU_STACK_API_KEY') | mandatory('LLM_GPU_STACK_API_KEY env var is required') }}"
        eval_runner_hf_token: "{{ lookup('env', 'HF_TOKEN') | mandatory('HF_TOKEN env var is required') }}"
        # Publishing to Nextcloud (eval-run publish). Only the app password is
        # secret; until it exists in OpenBao it's empty and publish says it isn't
        # configured, without failing the deploy.
        eval_runner_nextcloud_url: "https://nextcloud.{{ lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true) }}"
        eval_runner_nextcloud_user: eval-reports
        eval_runner_nextcloud_app_password: "{{ lookup('env', 'NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD') | default('', true) }}"
        eval_runner_table_share_with: steve
      tasks:
        - name: Create eval-runner build and config directories
          ansible.builtin.file:
            path: "{{ item }}"
            state: directory
            mode: "0700"
          loop:
            - "{{ eval_runner_build_dir }}"
            - /etc/eval-runner

        # Owned by uid 1000: the image runs as its non-root `app` user (see the
        # Dockerfile), which writes results here through a bind mount.
        - name: Create eval-runner results directory
          ansible.builtin.file:
            path: /srv/eval-runner/results
            state: directory
            owner: "1000"
            group: "1000"
            mode: "0755"

        - name: Copy eval-runner build context (Dockerfile and image helpers)
          ansible.builtin.copy:
            src: "{{ eval_runner_source_dir }}/{{ item }}"
            dest: "{{ eval_runner_build_dir }}/{{ item }}"
            mode: "0644"
          loop:
            - Dockerfile
            - Dockerfile.agentbench
            - Dockerfile.agentbench-sandbox
            - Dockerfile.bfcl
            - agentbench-constraints.txt
            - agentbench.patch
            - agentbench_run.py
            - bfcl-constraints.txt
            - bfcl_run.py
            - mock_nextcloud.py
            - mock_openai.py
            - publish.py
            - repobench_run.py
            - runmeta.py
            - selftest.sh
            - selftest_checks.py
            - summarize.py
            - wrapper_common.py
            - wrapper_selftest.sh

        # Canonical copy lives with the docs; the image ships it so `eval-run
        # publish` can mirror it into Nextcloud next to the leaderboard.
        - name: Copy findings.md into the eval-runner build context
          ansible.builtin.copy:
            src: "{{ repo_root }}/docs/eval-runner/findings.md"
            dest: "{{ eval_runner_build_dir }}/findings.md"
            mode: "0644"

        # The first deploy (2026-10-01) ran the image as root with this volume
        # at /root/.cache; the non-root image uses eval-runner-hf instead. Safe
        # to drop: it only ever cached public/gated datasets, re-downloadable.
        - name: Remove the old root-owned HF cache volume
          community.docker.docker_volume:
            name: eval-runner-hf-cache
            state: absent

        # One image per harness (their pinned dependencies conflict), plus the
        # sandbox AgentBench starts one throwaway container of per episode.
        - name: Build eval-runner images
          community.docker.docker_image:
            name: "{{ item.name }}"
            tag: "{{ item.tag }}"
            source: build
            build:
              path: "{{ eval_runner_build_dir }}"
              dockerfile: "{{ item.dockerfile }}"
            force_source: true
          loop:
            - { name: eval-runner, tag: local, dockerfile: Dockerfile }
            - { name: eval-runner-bfcl, tag: local, dockerfile: Dockerfile.bfcl }
            - { name: eval-runner-agentbench, tag: local, dockerfile: Dockerfile.agentbench }
            - { name: local-os/default, tag: latest, dockerfile: Dockerfile.agentbench-sandbox }
          loop_control:
            label: "{{ item.name }}:{{ item.tag }}"

        # Every force_source rebuild leaves the previous image untagged; 13 of
        # those (plus 4 old deep-research builds) had filled /var/lib/docker
        # to 86% by 2026-10-01. Dangling only: tagged and in-use images stay.
        - name: Remove dangling images left by rebuilds
          community.docker.docker_prune:
            images: true
            images_filters:
              dangling: true

        - name: Install eval-runner env file
          ansible.builtin.copy:
            dest: /etc/eval-runner/eval-runner.env
            mode: "0600"
            content: |
              LLM_BASE_URL=http://{{ eval_runner_framework_host }}:8080
              OPENAI_API_KEY={{ eval_runner_llm_api_key }}
              HF_TOKEN={{ eval_runner_hf_token }}
              NEXTCLOUD_EVAL_REPORTS_URL={{ eval_runner_nextcloud_url }}
              NEXTCLOUD_EVAL_REPORTS_USER={{ eval_runner_nextcloud_user }}
              NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD={{ eval_runner_nextcloud_app_password }}
              NEXTCLOUD_EVAL_TABLE_SHARE_WITH={{ eval_runner_table_share_with }}
          no_log: true

        - name: Install eval-run script
          ansible.builtin.copy:
            src: "{{ eval_runner_source_dir }}/eval-run"
            dest: /usr/local/bin/eval-run
            mode: "0755"

        - name: Check Framework's llama-server is reachable with this key
          ansible.builtin.uri:
            url: "http://{{ eval_runner_framework_host }}:8080/v1/models"
            headers:
              Authorization: "Bearer {{ eval_runner_llm_api_key }}"
          register: eval_runner_models
          failed_when: false
          no_log: true

        - name: Report Framework reachability (non-fatal, Framework may be serving nothing right now)
          ansible.builtin.debug:
            msg: "Framework /v1/models returned HTTP {{ eval_runner_models.status | default('unreachable') }}"

        # Runs the real start/exec/check path against a stand-in server inside
        # each image -- no Framework, no GPU. Proves the gated GPQA download,
        # IFEval's nltk data, scoring, the request settings lm_eval sends
        # (max_tokens 8192, temperature 0), the empty-response flags, resume from
        # cache and server-change detection; then BFCL, AgentBench (two real
        # network-less sandbox episodes) and RepoBench (dataset download, raw
        # completions) end to end, each with its historical request shape and
        # resume, on every deploy.
        - name: Run eval-runner self-test
          ansible.builtin.command:
            argv:
              - /usr/local/bin/eval-run
              - selftest
          register: eval_runner_selftest
          changed_when: false
          failed_when: eval_runner_selftest.rc != 0 or 'all selftests OK' not in eval_runner_selftest.stdout

        - name: Show eval-runner self-test summary
          ansible.builtin.debug:
            msg: "{{ eval_runner_selftest.stdout_lines | select('match', '^(==|checks OK|check OK|.*selftest OK|all selftests OK|server )') | list }}"

    - name: Share eval-runner's Nextcloud Reports folder with steve
      hosts: all
      gather_facts: false
      vars:
        eval_runner_nextcloud_app_password: "{{ lookup('env', 'NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD') | default('', true) }}"
      roles:
        - role: nextcloud_folder_share
          when: eval_runner_nextcloud_app_password | length > 0
          vars:
            nextcloud_folder_share_base_url: "https://nextcloud.lab.gibbsgreatly.xyz"
            nextcloud_folder_share_owner_user: eval-reports
            nextcloud_folder_share_owner_password: "{{ eval_runner_nextcloud_app_password }}"
            nextcloud_folder_share_folder: "Reports/eval-runner"

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing, reordering or deleting any existing line in the playbook"
    - "Adding comments inside the env file content: block (they would be written into the file)"
    - "Running provision.sh or ansible-playbook against any host"

gates:
  - id: exact-appended-play
    cmd: "tail -n 175 terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml | sha256sum | cut -d' ' -f1"
    expect: "e486f3a22b7b8cf78384bd64b064872260acda32b62f61c16f6b5207f83f7821"
    critical: true
  - id: append-only
    cmd: "git diff --numstat stable -- terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    expect: "176\\t0\\tterraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    critical: true
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check -i localhost, terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    expect: "exit 0"
    critical: true
```

### eval-runner-09-nextcloud-tables-and-account

```yaml
id: eval-runner-09-nextcloud-tables-and-account
title: Install Tables and create the eval-reports account in deploy-nextcloud-stack.yml
depends_on: []

change: |
  In terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml, insert exactly this block at the end of the
  first play's tasks: immediately after the "Ensure the steve local account
  exists and is an admin" task (after its "when: not ansible_check_mode"
  line) and before the blank line preceding the "Provision the dedicated
  GVM credentialed-scan account" play. Keep a blank line between this
  block and that next play. It is shown indented by 4 spaces below; in
  the playbook the comment and "- name:" lines sit at 4 spaces:

        # Nextcloud Tables: eval-runner's "Model evaluations" table
        # (docs/eval-runner/plan.md). app:install takes the newest release
        # compatible with this Nextcloud (2.3.1 on 35.x as of 2026-10-01); there
        # is no version pin, later updates come through normal app updates.
        - name: Install the Nextcloud Tables app
          ansible.builtin.command:
            cmd: docker exec --user www-data nextcloud-stack-app php occ app:install tables
          register: occ_install_tables
          changed_when: "'installed' in occ_install_tables.stdout and 'already installed' not in occ_install_tables.stdout"
          failed_when: occ_install_tables.rc != 0 and 'already installed' not in occ_install_tables.stdout
          when: not ansible_check_mode

        - name: Enable the Nextcloud Tables app
          ansible.builtin.command:
            cmd: docker exec --user www-data nextcloud-stack-app php occ app:enable tables
          register: occ_enable_tables
          changed_when: "'already enabled' not in occ_enable_tables.stdout"
          when: not ansible_check_mode

        # Service account eval-runner publishes as. Its login password is random
        # and never stored: only an app password is used, created by the operator
        # straight into OpenBao (docs/eval-runner/plan.md). -e forwards OC_PASS
        # into the container; docker exec doesn't pass the host environment on
        # its own.
        - name: Ensure the eval-reports service account exists
          ansible.builtin.command:
            cmd: >-
              docker exec -e OC_PASS --user www-data nextcloud-stack-app php occ user:add
              --password-from-env --display-name=eval-runner eval-reports
          environment:
            OC_PASS: "{{ lookup('ansible.builtin.password', '/dev/null', length=40, chars=['ascii_letters', 'digits']) }}"
          register: occ_add_eval_reports
          changed_when: >-
            'already exists' not in occ_add_eval_reports.stdout and
            'already exists' not in occ_add_eval_reports.stderr
          failed_when: >-
            occ_add_eval_reports.rc != 0 and
            'already exists' not in occ_add_eval_reports.stdout and
            'already exists' not in occ_add_eval_reports.stderr
          no_log: true
          when: not ansible_check_mode

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing or deleting any existing line (the existing steve task's missing -e OC_PASS is out of scope)"
    - "Running provision.sh or ansible-playbook against any host"

gates:
  - id: block-present
    cmd: "python3 -c \"s=open('terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml').read(); print('OK' if s.count('- name: Install the Nextcloud Tables app')==1 and s.count('- name: Enable the Nextcloud Tables app')==1 and s.count('- name: Ensure the eval-reports service account exists')==1 and s.count('docker exec -e OC_PASS --user www-data nextcloud-stack-app php occ user:add')==1 else 'MISSING')\""
    expect: "OK"
    critical: true
  - id: insert-only
    cmd: "git diff --numstat stable -- terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml"
    expect: "42\\t0\\tterraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml"
    critical: true
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check -i localhost, terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml"
    expect: "exit 0"
    critical: true
```

### eval-runner-10-manifest-nextcloud-app-password

```yaml
id: eval-runner-10-manifest-nextcloud-app-password
title: Declare NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD in the secrets manifest
depends_on:
  - eval-runner-09-nextcloud-tables-and-account

change: >
  In secrets/manifest.json, in the "services/nextcloud" entry's "fields"
  list, replace the exact text "NEXTCLOUD_DR_REPORTS_WEBDAV_URL", with
  "NEXTCLOUD_DR_REPORTS_WEBDAV_URL", "NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD",
  (one insertion, same quoting and spacing). Change nothing else. Do this
  only after the eval-reports account exists (operator deploy below), and
  have the operator write the value immediately after: until then every
  ./with-secrets* load on the branch fails closed.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any other edit to secrets/manifest.json"
    - "Running ./with-secrets*, openbao_write.py, provision.sh or ansible-playbook"

gates:
  - id: only-app-password-added
    cmd: "python3 -c \"import json,subprocess; e='services/nextcloud'; new=json.load(open('secrets/manifest.json'))['entries'][e]; old=json.loads(subprocess.check_output(['git','show','stable:secrets/manifest.json']))['entries'][e]; f=new['fields']; assert f.count('NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD')==1; f.remove('NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD'); assert new==old; print('OK')\""
    expect: "prints OK, exit 0"
    critical: true
```

### eval-runner-05-battery-doc-pointer

```yaml
id: eval-runner-05-battery-doc-pointer
title: Point the eval-battery doc at eval-runner
depends_on:
  - eval-runner-04-playbook-play

change: |
  Append to the end of docs/framework/eval-battery-phase2-plan.md exactly
  this text (it begins with one blank line). It is shown indented by
  4 spaces below; in the doc it starts at column 0:

    ## Running GPQA/IFEval from eval-runner (2026-10)

    GPQA and IFEval no longer run on `framework` or garuda. They run from the
    `eval-runner` image on `ai-services-stack` (`ai_seg`), as an HTTP client
    of whatever model Framework's llama-server is serving on `:8080`. Use
    `eval-run gpqa|ifeval [--pilot] [--concurrency N]` on that CT. It pins the
    same lm_eval 0.4.12 and `--gen_kwargs max_gen_toks=8192` as every result
    above, so new numbers stay comparable. Setup and usage:
    `docs/eval-runner/plan.md`.

    Other `eval-run` commands:
    - `eval-run selftest` checks the whole harness without Framework or the
      GPU.
    - `eval-run results` prints scores plus response-quality flags.
    - `eval-run resume <run>` continues an interrupted run from its cache.

    Every request is greedy (`temperature: 0` from both task configs, as in
    all the results above).

    **Finding from the new flags, applied to existing data (2026-10-01).**
    Qwen3.6-35B's GPQA redo, the 57.07% leader above, has **49 of 198
    questions with an empty response**, and 54 where flexible-extract found
    no answer letter. Its IFEval redo has 16 of 541 empty. That is the
    signature of reasoning using up the 8192-token budget before an answer
    is written. So 57.07% is a floor on its GPQA capability under this
    budget, not a ceiling. Compare reasoning models' GPQA numbers with that
    in mind, and check `eval-run results`' `empty` count on every new run.

scope:
  allowed_paths:
    - docs/framework/eval-battery-phase2-plan.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing any existing line of the doc"

gates:
  - id: section-present
    cmd: "grep -c '^## Running GPQA/IFEval from eval-runner (2026-10)$' docs/framework/eval-battery-phase2-plan.md"
    expect: "1"
    critical: true
  - id: append-only
    cmd: "git diff --numstat stable -- docs/framework/eval-battery-phase2-plan.md | cut -f2"
    expect: "0"
    critical: true
```

### eval-runner-07-stack-yaml-pointer

```yaml
id: eval-runner-07-stack-yaml-pointer
title: Note eval-runner in ai-services-stack's stack.yaml header
depends_on: []

change: |
  In terraform/lxc/stacks/ai-services-stack/stack.yaml, insert exactly
  these comment lines immediately above the line "hostname: ai-services-stack"
  (they continue the existing header comment). It is shown indented by
  4 spaces below; in the file each line starts at column 0 with "#":

    #
    # eval-runner added 2026-10-01 (docs/eval-runner/plan.md): a one-shot
    # lm_eval image + /usr/local/bin/eval-run for the eval battery's GPQA and
    # IFEval runs against Framework's llama-server. Not a compose service and
    # no published port; installed by its own play at the end of
    # deploy-ai-services-stack.yml.

scope:
  allowed_paths:
    - terraform/lxc/stacks/ai-services-stack/stack.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing any non-comment line (tags, resources, etc.)"

gates:
  - id: comment-only
    cmd: "git diff -U0 stable -- terraform/lxc/stacks/ai-services-stack/stack.yaml | grep '^+[^+]' | grep -vc '^+#'"
    expect: "0"
    critical: true
  - id: six-lines-added
    cmd: "git diff --numstat stable -- terraform/lxc/stacks/ai-services-stack/stack.yaml"
    expect: "6\\t0\\tterraform/lxc/stacks/ai-services-stack/stack.yaml"
    critical: true
```

### Operator: deploy to pve-tiny

This changes an Ansible play, so validation runs directly on `pve-tiny`
under the production approval flow. It needs every step above plus the
HF_TOKEN write. The redeploy re-runs the whole ai-services play, so
OpenWebUI and deep-research restart briefly; don't deploy during a
deep-research job.

```bash
export TASK_APPROVAL=eval-runner-deploy
./with-secrets-prod-tiny scripts/provision.sh --stack ai-services-stack
```

Pass criteria:
- The recap shows `failed=0`.
- The eval-runner play prints `Framework /v1/models returned HTTP 200`
  (non-fatal if Framework is down).
- `Show eval-runner self-test summary` lists stages 1–4 and ends with
  `selftest OK`.

The self-test never touches Framework.

### Operator: Nextcloud side (done 2026-10-01)

In order:

1. Deploy `nextcloud-stack` on `pve` (installs and enables Tables, and
   creates `eval-reports`):

   ```bash
   export TASK_APPROVAL=eval-runner-nextcloud-publish
   ./with-secrets-prod scripts/provision.sh --stack nextcloud-stack
   ```

2. Land step `eval-runner-10`, then straight away create the app password
   and write it into OpenBao without ever displaying it. The `grep` only
   passes a token-shaped value, so an `occ` error stores nothing:

   ```bash
   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
   ssh root@192.168.120.10 'docker exec --user www-data nextcloud-stack-app php occ user:auth-tokens:add -n --name=eval-runner eval-reports' \
     | tail -n 1 | tr -d '\r' | grep -E '^[A-Za-z0-9]{40,}$' \
     | LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/nextcloud NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD
   unset BAO_TOKEN
   ```

3. Redeploy `ai-services-stack` (the deploy section above), then run
   `ssh root@192.168.50.11 eval-run publish`. A second run must report
   `0 rows created, 0 updated`.
4. Optional cleanup: delete the auto-created "Welcome to Nextcloud
   Tables!" table owned by `eval-reports`.

### Operator (one-off, done 2026-10-01): import historical results

This copies the Ollama-era GPQA/IFEval result and sample files (~42 MB)
from framework into `_historical/`, so `eval-run results` shows them for
comparison. `summarize.py` decides at display time which ones are
comparable. Run from the workstation:

```bash
H=$(mktemp -d)/_historical; mkdir -p "$H"
ssh steve@framework.gibbsgreatly.xyz 'cd ~/eval-harnesses/results && find . \( -name "results_*.json" -o -name "samples_gpqa_diamond_cot_zeroshot_*.jsonl" -o -name "samples_ifeval_*.jsonl" \) -print0 | xargs -0 tar cf - --' | tar xf - -C "$H"
python3 - "$H" <<'PY'
import glob, json, os, sys
for f in glob.glob(sys.argv[1] + "/**/results_*.json", recursive=True):
    if not any(t in ("gpqa_diamond_cot_zeroshot", "ifeval") for t in json.load(open(f)).get("results", {})):
        os.remove(f)
PY
tar cf - -C "$(dirname "$H")" _historical | ssh root@192.168.50.11 'tar xf - -C /srv/eval-runner/results/ && chown -R 1000:1000 /srv/eval-runner/results/_historical'
```

### Operator (one-off): import historical BFCL and AgentBench results

18 BFCL scores (framework's BFCL venv) and 2 AgentBench outputs (garuda)
become eval-runner results files under `_historical/`. Run from the
workstation (repo root):

```bash
D=terraform/lxc/ansible/files/eval-runner; H=$(mktemp -d)
scp $D/import_history.py framework.gibbsgreatly.xyz:/tmp/
ssh framework.gibbsgreatly.xyz '~/bfcl-eval/venv/bin/python /tmp/import_history.py probe-bfcl ~/bfcl-eval/venv/lib/python3.14/site-packages; rm /tmp/import_history.py' > "$H/bfcl.json"
python3 $D/import_history.py bfcl "$H/bfcl.json" "$H/out"
python3 $D/import_history.py agentbench ~/eval-harnesses/AgentBench/outputs "$H/out"
tar cf - -C "$H/out" _historical | ssh root@192.168.50.11 'tar xf - -C /srv/eval-runner/results/ && chown -R 1000:1000 /srv/eval-runner/results/_historical'
```

## Using it

```bash
ssh root@192.168.50.11
eval-run selftest                         # ~30 s; no Framework, no GPU
eval-run results                          # scores + empty/unparsed flags per run
eval-run gpqa --pilot --note "reasoning_effort=high"   # 40 questions: GPU for ~1-2 h
eval-run ifeval --note "..."              # full IFEval (541): many hours
eval-run bfcl                             # BFCL simple (400 cases)
eval-run agentbench                       # AgentBench os-std (100 episodes, sandboxes on this CT)
eval-run repobench                        # RepoBench (rebuilt): 1500 completions, prompts up to 16k
eval-run resume <run>                     # continue an interrupted run from its cache
eval-run publish                          # push everything to Nextcloud (idempotent)
eval-run publish --dry-run                # render into results/_publish-preview instead
docker ps --filter name=^eval-            # what's running (one real run at a time, enforced)
```

**Before starting any real run:**
- Check nothing else is using Framework: `/slots`, CyberSecEval jobs, or
  deep-research. A second client roughly halves per-request speed.
- Record server settings the API can't show (llama-server
  `--chat-template-kwargs`, for example) with `--note`.

**Results:**
- Each run lives in `/srv/eval-runner/results/<model>-<task>[-pilot]-<UTC>/`:
  - `run.json`: server fingerprint, note, exact lm_eval argv
  - `cache/`: the resume database
  - `<model>/results_*.json` and `samples_*.jsonl`
- A non-zero `empty` count means some answers never arrived, usually
  because reasoning used up the 8192-token budget. Read the samples before
  quoting the score.
- For reasoning models that run out of budget at 8192 (many empty
  answers), a second run with `--max-gen-toks 32768` gives the 32k
  series. Expect several times the 8192 run's duration.
- After a run, run `eval-run publish`. The Nextcloud table, leaderboard
  and per-run report are the record from then on. Update
  `docs/eval-runner/findings.md` by hand when a result changes the
  analysis, and redeploy to mirror it.
- Remove finished containers with `docker rm eval-<run>`.

## Out of scope / follow-ups

- **Historical numbers with no surviving data** (listed in
  `findings.md`, not importable): the six RepoBench results (scripts and
  outputs were on the deleted ai-stack LXC) and the AgentBench numbers
  run from ai-stack (Gemma4-26B, the A4B-QAT, Qwen3-Coder-Next,
  Laguna-Heretic).
- **Nextcloud Office** for opening `leaderboard.xlsx` in the browser:
  the `eurooffice` app is enabled but has no Document Server. That is a
  proposal in `README.md`, not part of this plan.
- **Longer retention than PBS keep-last-2,** if wanted: a private
  Nextcloud push. GPQA's terms forbid public sharing of samples.
- **Running from the CyberSecEval panel** as another job type.
