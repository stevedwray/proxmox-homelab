# eval-runner: GPQA/IFEval from ai-services-stack

Status: **all steps done and deployed to pve-tiny (2026-10-01).** The
deploy-time self-test passes. The literal content and hashes below match
the files as deployed. See `README.md` for hand-backs.

## Goal

Run the lm_eval-based tests from the eval battery
(`docs/framework/eval-battery-phase2-plan.md`): GPQA (diamond, CoT
zero-shot) and IFEval. They run from `ai-services-stack` against whatever
model Framework's llama-server is serving on `:8080`, instead of on
`framework` itself or garuda. The whole harness has to be verifiable
without using Framework's GPU.

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
- **`HF_TOKEN` goes in `shared/external-apis`.** GPQA is gated (anonymous
  fetch: HTTP 401). Framework's key is the existing
  `LLM_GPU_STACK_API_KEY`.

## Facts checked (2026-10-01)

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
- **Wrapper:** `ai-services-stack` is on `pve-tiny`, so deploys use
  `./with-secrets-prod-tiny`.

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
    cmd: "python3 -c \"import json,subprocess; new=json.load(open('secrets/manifest.json')); old=json.loads(subprocess.check_output(['git','show','stable:secrets/manifest.json'])); f=new['entries']['shared/external-apis']['fields']; assert f.count('HF_TOKEN')==1; f.remove('HF_TOKEN'); assert new==old; print('OK')\""
    expect: "prints OK, exit 0"
    critical: true
  - id: one-line-diff
    cmd: "git diff --numstat stable -- secrets/manifest.json"
    expect: "1\t1\tsecrets/manifest.json"
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
    # rouge-score, sqlitedict and word2number only ship as sdists.
    RUN pip install --no-cache-dir \
          "aiohttp==3.14.3" \
          "datasets==5.0.1" \
          "immutabledict==4.3.1" \
          "langdetect==1.0.9" \
          "lm_eval[api,ifeval]==0.4.12" \
          "nltk==3.10.1" \
          "tenacity==9.1.4"

    # Run setup (runmeta.py), scoring summary (summarize.py) and the selftest
    # pieces. Copied after the pip layer so editing them doesn't invalidate the
    # slow install. The test_*.py unit tests stay in the repo, not the image.
    COPY mock_openai.py runmeta.py selftest.sh selftest_checks.py summarize.py /opt/eval-runner/
    RUN chmod 0755 /opt/eval-runner/selftest.sh

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
    expect: "4a131859b8572dfd3b3606fe7977d7d8c4e8498879313c07103a70b2d8f858e7"
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
    # eval-run -- start, resume, self-test and summarise lm_eval GPQA/IFEval
    # runs against whatever model Framework's llama-server is serving right
    # now. Installed by deploy-ai-services-stack.yml's "Install eval-runner"
    # play; see docs/eval-runner/plan.md. Secrets never pass through this
    # script: containers get them only via --env-file.
    set -euo pipefail

    ENV_FILE=/etc/eval-runner/eval-runner.env
    RESULTS_DIR=/srv/eval-runner/results
    IMAGE=eval-runner:local
    HF_VOLUME=eval-runner-hf:/home/app/.cache/huggingface

    usage() {
      cat <<'USAGE'
    Usage: eval-run <gpqa|ifeval> [--pilot] [--concurrency N] [--note TEXT]
           eval-run resume <run> [--force]
           eval-run selftest
           eval-run results [run...]

    gpqa|ifeval  Start one detached run (container eval-<run>) against the model
                 Framework's llama-server is serving. Uses Framework's GPU for
                 hours -- check nothing else needs it first.
      --pilot          40 examples (--limit 40) instead of the full task
      --concurrency N  parallel requests (default 1, as every historical result)
      --note TEXT      stored in run.json. Use it for server settings the API
                       can't show, e.g. "reasoning_effort=high"
    resume       Re-run an interrupted run. Answers already received are
                 replayed from its cache. Refuses if the server's fingerprint
                 (model, build, sampling defaults, chat template) has changed,
                 unless --force.
    selftest     Exercise the whole harness against a stand-in server inside
                 the image (no Framework, no GPU). Exits non-zero on failure.
    results      Headline scores and response-quality flags per run.
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

    launch() {
      local run="$1"
      docker run -d --name "eval-${run}" \
        --env-file "$ENV_FILE" \
        -v "${RESULTS_DIR}:/results" \
        -v "$HF_VOLUME" \
        --entrypoint python \
        "$IMAGE" /opt/eval-runner/runmeta.py exec "/results/${run}" >/dev/null
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
      local concurrency=1 note=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --pilot) extra+=(--pilot); shift ;;
          --concurrency) concurrency="${2:?--concurrency needs a value}"; shift 2 ;;
          --note) note="${2?--note needs a value}"; shift 2 ;;
          *) usage >&2; exit 2 ;;
        esac
      done
      [[ "$concurrency" =~ ^[1-9][0-9]*$ ]] || die "--concurrency must be a positive integer"
      refuse_if_running

      local run
      run=$(helper /opt/eval-runner/runmeta.py start --task "$short" "${extra[@]}" \
        --concurrency "$concurrency" --note "$note")
      launch "$run"
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
      launch "$run"
    }

    [[ $# -ge 1 ]] || { usage >&2; exit 2; }
    case "$1" in
      gpqa|ifeval)
        cmd_start "$@"
        ;;
      resume)
        shift
        cmd_resume "$@"
        ;;
      selftest)
        [[ $# -eq 1 ]] || { usage >&2; exit 2; }
        exec docker run --rm \
          --env-file "$ENV_FILE" \
          -e "SELFTEST_RUN=$(date -u +%Y%m%dT%H%M%SZ)" \
          -v "${RESULTS_DIR}:/results" \
          -v "$HF_VOLUME" \
          --entrypoint /bin/sh \
          "$IMAGE" /opt/eval-runner/selftest.sh
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
    expect: "385f355ddc242ee33f6b68c6a4ce2f78081665ec0c51350619bdb0648b54bcd2"
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
    result files, response cache) can be exercised without touching
    Framework's GPU. Listens on 127.0.0.1 only, inside the selftest container.

    Environment:
      MOCK_PORT          listen port (default 18080)
      MOCK_MODEL         model id served on /v1/models (default selftest-mock)
      MOCK_MODEL_PATH    model_path reported on /props -- change it to make a
                         second instance look like a different server
      MOCK_REQUEST_LOG   if set, append every chat-completion request body as
                         one JSON line (selftest asserts on what lm_eval sent)
      MOCK_EMPTY_EVERY   if N > 0, every Nth reply has empty content (the
                         "reasoning ate the token budget" failure shape), so
                         the empty-response flags can be checked
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
    REPLY = "Let me think step by step. The answer is (A)."

    PROPS = {
        "model_path": MODEL_PATH,
        "model_alias": MODEL,
        "build_info": "selftest-mock",
        "total_slots": 1,
        "chat_template": "{{ messages }}",
        "default_generation_settings": {
            "n_ctx": 4096,
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
            if self.path.rstrip("/") != "/v1/chat/completions":
                self._send(404, {"error": "not found"})
                return
            with _lock:
                _count += 1
                n = _count
                if REQUEST_LOG:
                    with open(REQUEST_LOG, "a") as fh:
                        fh.write(json.dumps(json.loads(raw)) + "\n")
            content = "" if EMPTY_EVERY > 0 and n % EMPTY_EVERY == 0 else REPLY
            self._send(200, {
                "id": f"selftest-{n}",
                "object": "chat.completion",
                "model": MODEL,
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
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
    expect: "ce822cf5576601ded4e733b110fecb0bd40dbe0d7d7cc498cd2dad32268bc885"
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
    expect: "d83b8e643d27ebb80ddaae6eaf076a18b1b438a0f1c63432d407efdd622e6be8"
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

    """Print headline GPQA/IFEval numbers for eval-run result directories.

    With no arguments, summarises every run directory under /results except
    those starting with "_" (selftest output). With --check, exits non-zero
    unless every given directory holds results for both tasks with numeric
    headline metrics -- the selftest uses this as one of its checks.

    Each task also gets response-quality flags read from its samples file,
    counted per question:
      empty     the raw response was empty -- typically a reasoning model that
                used its whole token budget thinking, so the answer never came
      unparsed  (GPQA only) flexible-extract found no answer letter
    Treat a score with many of either as an infrastructure/config problem to
    inspect, not as the model's capability.
    """

    import argparse
    import glob
    import json
    import os
    import sys

    RESULTS_ROOT = "/results"

    HEADLINE = {
        "gpqa_diamond_cot_zeroshot": [
            ("GPQA flex", "exact_match,flexible-extract"),
            ("GPQA strict", "exact_match,strict-match"),
        ],
        "ifeval": [
            ("IFEval p-strict", "prompt_level_strict_acc,none"),
            ("IFEval p-loose", "prompt_level_loose_acc,none"),
        ],
    }


    def _results_stamp(path):
        """results_<stamp>.json -> <stamp>, shared with that run's samples files."""
        return os.path.basename(path)[len("results_"):-len(".json")]


    def load(run_dir):
        """Map task -> {metrics, n, samples}, the newest results file winning."""
        found = {}
        pattern = os.path.join(run_dir, "**", "results_*.json")
        for path in sorted(glob.glob(pattern, recursive=True)):
            with open(path) as fh:
                data = json.load(fh)
            stamp = _results_stamp(path)
            for task, metrics in data.get("results", {}).items():
                if task in HEADLINE:
                    samples = os.path.join(os.path.dirname(path), f"samples_{task}_{stamp}.jsonl")
                    found[task] = {
                        "metrics": metrics,
                        "n": data.get("n-samples", {}).get(task, {}).get("effective"),
                        "samples": samples if os.path.exists(samples) else None,
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


    def _flag_text(samples, task):
        if not samples:
            return "[no samples file]"
        flags = response_flags(samples, task)
        text = f"empty {flags['empty']}"
        if flags["unparsed"] is not None:
            text += f", unparsed {flags['unparsed']}"
        if flags["empty"] or flags["unparsed"]:
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
        parts.append(_flag_text(entry["samples"], task))
        return parts, ok


    def describe(run_dir, check):
        """Return (line, ok) for one run directory."""
        name = os.path.basename(os.path.normpath(run_dir))
        found = load(run_dir)
        if not found:
            return f"{name}: no results yet (still running, or failed)", False
        ok = True
        parts = []
        for task in HEADLINE:
            if task not in found:
                ok = ok and not check
                continue
            task_text, task_ok = task_parts(task, found[task])
            parts += task_text
            ok = ok and task_ok
        return f"{name}: " + ", ".join(parts), ok


    def main(argv=None):
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--check", action="store_true")
        parser.add_argument("dirs", nargs="*")
        args = parser.parse_args(argv)

        dirs = args.dirs or sorted(
            d for d in glob.glob(os.path.join(RESULTS_ROOT, "*"))
            if os.path.isdir(d) and not os.path.basename(d).startswith("_")
        )
        if not dirs:
            print("no runs yet")
            return 0

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
    expect: "6ea81f6de43b494f0917e1e0b7f25bbd488501f2d48c788b2bc4f38a9c9083df"
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
    }
    PILOT_LIMIT = 40
    MAX_GEN_TOKS = 8192
    REQUEST_TIMEOUT = 3600
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


    def run_name(model_id, task, pilot, stamp):
        parts = [safe_name(model_id), task] + (["pilot"] if pilot else []) + [stamp]
        return "-".join(parts)


    def lm_eval_argv(base_url, model_id, tasks, concurrency, limit, run_dir):
        argv = [
            "lm_eval", "run",
            "--model", "local-chat-completions",
            "--model_args",
            f"base_url={base_url}/v1/chat/completions,model={model_id},"
            f"num_concurrent={concurrency},tokenized_requests=False,timeout={REQUEST_TIMEOUT}",
            "--tasks", ",".join(tasks),
            "--apply_chat_template", "--log_samples",
            "--gen_kwargs", f"max_gen_toks={MAX_GEN_TOKS}",
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


    def build_record(server, task, pilot, limit, concurrency, note, stamp, results_root):
        if limit is None and pilot:
            limit = PILOT_LIMIT
        name = run_name(server["model_id"], task, pilot, stamp)
        run_dir = os.path.join(results_root, name)
        return {
            "run": name,
            "task": task,
            "tasks": TASKS[task],
            "pilot": pilot,
            "limit": limit,
            "concurrency": concurrency,
            "note": note,
            "created_utc": stamp,
            "lm_eval_version": _lm_eval_version(),
            "server": server,
            "fingerprint": fingerprint(server),
            "lm_eval_argv": lm_eval_argv(server["base_url"], server["model_id"], TASKS[task], concurrency, limit, run_dir),
        }, run_dir


    def load_record(run_dir):
        with open(os.path.join(run_dir, "run.json")) as fh:
            return json.load(fh)


    def cmd_start(args):
        server = snapshot_server(args.base_url, os.environ.get("OPENAI_API_KEY", ""))
        record, run_dir = build_record(
            server, args.task, args.pilot, args.limit, args.concurrency, args.note,
            args.stamp or _now_stamp(), args.results_root,
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
        start.add_argument("--stamp")
        start.add_argument("--results-root", default="/results")

        run_exec = sub.add_parser("exec")
        run_exec.add_argument("run_dir")

        check = sub.add_parser("check")
        check.add_argument("run_dir")
        check.add_argument("--base-url")

        args = parser.parse_args(argv)
        if args.cmd == "start":
            if not args.base_url:
                parser.error("--base-url or LLM_BASE_URL is required")
            if args.concurrency < 1:
                parser.error("--concurrency must be >= 1")
            return cmd_start(args)
        if args.cmd == "exec":
            return cmd_exec(args)
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
    expect: "09d626fb2053e57640968c75f6bf6337726d8f944353fac8058f46b1a252ac8c"
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
    """

    import argparse
    import json
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


    def flag_errors(run_dir, expected_empty):
        errors = []
        found = summarize.load(run_dir)
        total_empty = 0
        for task in summarize.HEADLINE:
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


    def main(argv=None):
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--requests", required=True)
        parser.add_argument("--expect-requests", type=int, required=True)
        parser.add_argument("--model", required=True)
        parser.add_argument("--run-dir")
        parser.add_argument("--expect-empty", type=int)
        args = parser.parse_args(argv)

        errors = request_errors(args.requests, args.expect_requests, args.model)
        if args.run_dir is not None:
            errors += flag_errors(args.run_dir, args.expect_empty)
        for line in errors:
            print(f"FAIL: {line}", file=sys.stderr)
        if errors:
            return 1
        print(f"checks OK ({args.expect_requests} requests)")
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
    expect: "c58fa4baa59293aefebd0b15e9f56298a47a7dc5383066915251b24f18718ad5"
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
    expect: "60a4ab5df24177735a98fca7a09a22e63bd8b8c3a7e01707fc70fd6e12ac7b49"
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


    def write_run(root, name, tasks, gpqa_rows=None, ifeval_rows=None, run_json=True):
        """Create a run dir shaped like lm_eval's output (<run>/<model>/results_*.json)."""
        run_dir = os.path.join(root, name)
        model_dir = os.path.join(run_dir, "model")
        os.makedirs(model_dir)
        results = {}
        n_samples = {}
        if "gpqa" in tasks:
            results["gpqa_diamond_cot_zeroshot"] = {"exact_match,flexible-extract": 0.5, "exact_match,strict-match": 0.25}
            n_samples["gpqa_diamond_cot_zeroshot"] = {"original": 198, "effective": len(gpqa_rows or [])}
        if "ifeval" in tasks:
            results["ifeval"] = {"prompt_level_strict_acc,none": 0.9, "prompt_level_loose_acc,none": 0.95}
            n_samples["ifeval"] = {"original": 541, "effective": len(ifeval_rows or [])}
        with open(os.path.join(model_dir, f"results_{STAMP}.json"), "w") as fh:
            json.dump({"results": results, "n-samples": n_samples}, fh)
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
    expect: "1d1ef80633862b7bc812a75f8af10e0fddfa1f421692ed7485d899d12c2601b2"
    critical: true
  - id: unit-tests
    cmd: "python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner/ -p 'test_*.py' 2>&1 | tail -1"
    expect: "OK"
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

change: |
  Append to the end of terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml
  one blank line followed by exactly this content (a new, separate play;
  do not edit or move any existing line in the file). It is shown
  indented by 4 spaces below; in the playbook the play starts at
  column 0 ("- name:"):

    - name: Install eval-runner (lm_eval GPQA/IFEval against Framework's llama-server)
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
            - mock_openai.py
            - runmeta.py
            - selftest.sh
            - selftest_checks.py
            - summarize.py

        # The first deploy (2026-10-01) ran the image as root with this volume
        # at /root/.cache; the non-root image uses eval-runner-hf instead. Safe
        # to drop: it only ever cached public/gated datasets, re-downloadable.
        - name: Remove the old root-owned HF cache volume
          community.docker.docker_volume:
            name: eval-runner-hf-cache
            state: absent

        - name: Build eval-runner image
          community.docker.docker_image:
            name: eval-runner
            tag: local
            source: build
            build:
              path: "{{ eval_runner_build_dir }}"
            force_source: true

        - name: Install eval-runner env file
          ansible.builtin.copy:
            dest: /etc/eval-runner/eval-runner.env
            mode: "0600"
            content: |
              LLM_BASE_URL=http://{{ eval_runner_framework_host }}:8080
              OPENAI_API_KEY={{ eval_runner_llm_api_key }}
              HF_TOKEN={{ eval_runner_hf_token }}
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
        # the image -- no Framework, no GPU. Proves the gated GPQA download,
        # IFEval's nltk data, scoring, the request settings lm_eval sends
        # (max_tokens 8192, temperature 0), the empty-response flags, resume from
        # cache, and server-change detection on every deploy.
        - name: Run eval-runner self-test
          ansible.builtin.command:
            argv:
              - /usr/local/bin/eval-run
              - selftest
          register: eval_runner_selftest
          changed_when: false
          failed_when: eval_runner_selftest.rc != 0 or 'selftest OK' not in eval_runner_selftest.stdout

        - name: Show eval-runner self-test summary
          ansible.builtin.debug:
            msg: "{{ eval_runner_selftest.stdout_lines | select('match', '^(==|checks OK|check OK|selftest OK|server )') | list }}"

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
    cmd: "tail -n 107 terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml | sha256sum | cut -d' ' -f1"
    expect: "7e23680c7929de606ebb61db1197b5a41642b9140a172e89e5af810ea9c57a6b"
    critical: true
  - id: append-only
    cmd: "git diff --numstat stable -- terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    expect: "108\\t0\\tterraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    critical: true
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check -i localhost, terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    expect: "exit 0"
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

## Using it

```bash
ssh root@192.168.50.11
eval-run selftest                         # ~30 s; no Framework, no GPU
eval-run results                          # scores + empty/unparsed flags per run
eval-run gpqa --pilot --note "reasoning_effort=high"   # 40 questions: GPU for ~1-2 h
eval-run ifeval --note "..."              # full IFEval (541): many hours
eval-run resume <run>                     # continue an interrupted run from its cache
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
- Record headline numbers in the eval-battery doc's Phase 1 table, as
  before. Remove finished containers with `docker rm eval-<run>`.

## Out of scope / follow-ups

- **RepoBench, BFCL and AgentBench.** Their harnesses live on garuda, or
  lived on the deleted `ai-stack` LXC (VMID 116). lm_eval's
  `longbench_repobench-p` is a different RepoBench variant from the
  eval-battery table's.
- **A comparison table of historical results** in `eval-run results`
  (curated: only the runs the eval-battery doc marks as valid).
- **Results durability.** Results are local to the CT (16 GB rootfs). The
  pve-tiny backup coverage is not yet confirmed; the alternative is a
  private Nextcloud push. GPQA's terms forbid public sharing of samples.
- **Running from the CyberSecEval panel** as another job type.
