# eval-runner: GPQA/IFEval from ai-services-stack

Status: **all steps done and deployed to pve-tiny (2026-10-01).** The
deploy self-test passes. The literal content and hashes below match the
files as deployed (commit `2793ec09` and later). See `README.md` for
hand-backs.

## Goal

Run the lm_eval-based tests from the eval battery
(`docs/framework/eval-battery-phase2-plan.md`): GPQA (diamond, CoT
zero-shot) and IFEval. They run from `ai-services-stack` against whatever
model Framework's llama-server is serving on `:8080`, instead of on
`framework` itself or garuda. The harness is verifiable without using
Framework's GPU at all.

## Decisions (resolved with the operator, 2026-10-01)

- **Host: `ai-services-stack`, not a new LXC.** A GPQA run occupies
  Framework anyway, so nobody is using the local-AI services at the same
  time and isolation buys nothing. The CT already sits in `ai_seg`. It is
  2 cores, 6 GB RAM, 16 GB rootfs and 24 GB Docker storage. lm_eval needs
  about 1–2 GB of RAM and a few GB of disk.
- **No model switching.** The runner is a client of whatever llama-server
  serves. `eval-run` reads the model id from `/v1/models`.
- **CyberSecEval is out of scope.** It has its own panel
  (`docs/cyberseceval-panel/`).
- **A one-shot Docker image plus a script, not a compose service.** The
  image is built by its own play. Each run is a detached `docker run`
  started by `/usr/local/bin/eval-run`, outside the
  `/opt/ai-services-stack` compose project. A
  `provision.sh --stack ai-services-stack` redeploy therefore never kills
  a 20-hour run.
- **Comparable with historical results.** lm_eval is pinned to 0.4.12,
  with the same API and IFEval dependency versions as the `framework`
  venv behind every number in the eval-battery doc. Every run also passes
  `--apply_chat_template --log_samples --gen_kwargs max_gen_toks=8192`
  (Bug 6), and the pilot size is `--limit 40`. `num_concurrent` defaults
  to 1; `--concurrency N` is opt-in.
- **Request timeout raised to 3600 s.** lm_eval's API client defaults to
  `timeout=300`, less than one 8192-token answer at about 18 tok/s.
- **Verifiable without the GPU.** `eval-run selftest` runs both tasks at
  `--limit 2` against `mock_openai.py`, a stand-in OpenAI-compatible
  server inside the image. That proves the gated dataset download,
  IFEval's nltk data, scoring and the result-file shape. The deploy runs
  it as a gate. Running real pilots against Framework is a separate,
  explicit operator decision, because it occupies the GPU for hours.
- **Non-root image (uid 1000),** matching deep-research. The results
  directory is chowned to 1000, and the HF cache lives in the
  `eval-runner-hf` volume at `/home/app/.cache/huggingface`.
- **`HF_TOKEN` goes in `shared/external-apis`.** GPQA's dataset is gated
  (anonymous fetch: HTTP 401). Framework's key is the existing
  `LLM_GPU_STACK_API_KEY` (`services/llm-gpu`).

## Facts checked (2026-10-01)

- **Network:** `ai_seg → framework:8080,11434` is already allowed
  (`mikrotik-firewall-framework-fqdn.yml`), and so is zone-wide
  `ai_seg → !192.168.0.0/16:443` (covers PyPI and Hugging Face). No
  firewall change is needed.
- **Build pattern:** matches deep-research and web-search-mcp. Source is
  in `terraform/lxc/ansible/files/<name>/`, copied by the playbook and
  built on the CT.
- **`OPENAI_API_KEY` name clash:** `shared/external-apis` contains a real
  `OPENAI_API_KEY`, and lm_eval reads that variable name. The runner only
  ever gets the explicitly written `/etc/eval-runner/eval-runner.env`
  (0600), which carries Framework's key under that name.
- **nltk 3.10.1 import guard:** imports that resolve under the cwd are
  refused, and the build's default cwd `/` contains the stdlib. Hence
  `WORKDIR /results` comes before the first `RUN` (found on the first
  real deploy).
- **Dependencies:** the pins resolve for Python 3.12 (72 packages, no
  torch, transformers or CUDA). `langdetect`, `rouge-score`, `sqlitedict`
  and `word2number` are sdist-only, so `--only-binary` isn't possible.
- **`summarize.py`** reproduces the eval-battery doc's Qwen3.6-35B numbers
  exactly (GPQA flex 57.07%, IFEval 90.39%/91.87%) from that run's
  historical `results_*.json`.
- **Wrapper:** `ai-services-stack` lives on `pve-tiny`. Deploys use
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
  trailing newline). It is shown indented by 4 spaces below; the
  file itself has no leading indentation:

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

    # Helpers used by `eval-run selftest` and `eval-run results` (copied after
    # the pip layer so editing them doesn't invalidate the slow install).
    COPY mock_openai.py selftest.sh summarize.py /opt/eval-runner/
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
    expect: "a834d6bc9dd7d9c205d6a7f58890333ed13b1b18913474b600b9f4b4ca0e96e2"
    critical: true
```
### eval-runner-03-eval-run-script

```yaml
id: eval-runner-03-eval-run-script
title: Add the eval-run launcher script
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/eval-run with exactly this content (byte for byte, including the
  trailing newline), then run chmod 0755 on it. It is shown indented by 4 spaces below; the
  file itself has no leading indentation:

    #!/usr/bin/env bash
    # eval-run -- start one lm_eval GPQA or IFEval run against whatever model
    # Framework's llama-server is serving right now. Installed by
    # deploy-ai-services-stack.yml's "Install eval-runner" play; see
    # docs/eval-runner/plan.md.
    set -euo pipefail

    ENV_FILE=/etc/eval-runner/eval-runner.env
    RESULTS_DIR=/srv/eval-runner/results
    IMAGE=eval-runner:local
    PILOT_LIMIT=40

    usage() {
      cat <<'USAGE'
    Usage: eval-run <gpqa|ifeval> [--pilot] [--concurrency N]
           eval-run selftest
           eval-run results [run-dir-name...]

    gpqa|ifeval  Start one detached container named eval-<run> against the model
                 Framework's llama-server is serving, and print how to follow it.
      --pilot          run 40 examples (--limit 40) instead of the full task
      --concurrency N  parallel requests to llama-server (default 1, which is
                       what every historical result used)
    selftest     Run both tasks at --limit 2 against a local stand-in server
                 inside the image (no Framework, no GPU) and check the result
                 files. Exits non-zero on failure.
    results      Print headline scores for every run (or the named ones).
    USAGE
    }

    [[ $# -ge 1 ]] || { usage >&2; exit 2; }
    case "$1" in
      selftest)
        [[ $# -eq 1 ]] || { usage >&2; exit 2; }
        exec docker run --rm \
          --env-file "$ENV_FILE" \
          -e "SELFTEST_RUN=$(date -u +%Y%m%dT%H%M%SZ)" \
          -v "${RESULTS_DIR}:/results" \
          -v eval-runner-hf:/home/app/.cache/huggingface \
          --entrypoint /bin/sh \
          "$IMAGE" /opt/eval-runner/selftest.sh
        ;;
      results)
        shift
        targets=()
        for name in "$@"; do
          targets+=("/results/${name}")
        done
        exec docker run --rm \
          -v "${RESULTS_DIR}:/results:ro" \
          --entrypoint python \
          "$IMAGE" /opt/eval-runner/summarize.py "${targets[@]}"
        ;;
    esac
    case "$1" in
      gpqa) task=gpqa_diamond_cot_zeroshot ;;
      ifeval) task=ifeval ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; exit 2 ;;
    esac
    short="$1"
    shift

    pilot=0
    concurrency=1
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --pilot) pilot=1; shift ;;
        --concurrency) concurrency="${2:?--concurrency needs a value}"; shift 2 ;;
        *) usage >&2; exit 2 ;;
      esac
    done
    [[ "$concurrency" =~ ^[1-9][0-9]*$ ]] || { echo "eval-run: --concurrency must be a positive integer" >&2; exit 2; }

    running=$(docker ps --filter 'name=^eval-' --format '{{.Names}}')
    if [[ -n "$running" ]]; then
      echo "eval-run: an eval is already running: $running" >&2
      exit 1
    fi

    # LLM_BASE_URL, OPENAI_API_KEY (Framework's llama-server key), HF_TOKEN
    # shellcheck source=/dev/null
    source "$ENV_FILE"

    model=$(curl -fsS -m 10 -H "Authorization: Bearer ${OPENAI_API_KEY}" "${LLM_BASE_URL}/v1/models" \
      | python3 -c 'import json, sys; print(json.load(sys.stdin)["data"][0]["id"])')
    safe_model=$(printf '%s' "$model" | tr -c 'A-Za-z0-9_.-' '-')

    run="${safe_model}-${short}"
    if [[ $pilot -eq 1 ]]; then
      run="${run}-pilot"
    fi
    run="${run}-$(date -u +%Y%m%dT%H%M%SZ)"

    limit_args=()
    if [[ $pilot -eq 1 ]]; then
      limit_args=(--limit "$PILOT_LIMIT")
    fi

    docker run -d --name "eval-${run}" \
      --env-file "$ENV_FILE" \
      -v "${RESULTS_DIR}:/results" \
      -v eval-runner-hf:/home/app/.cache/huggingface \
      "$IMAGE" run \
      --model local-chat-completions \
      --model_args "base_url=${LLM_BASE_URL}/v1/chat/completions,model=${model},num_concurrent=${concurrency},tokenized_requests=False,timeout=3600" \
      --tasks "$task" --apply_chat_template --log_samples \
      --gen_kwargs max_gen_toks=8192 \
      "${limit_args[@]}" \
      --output_path "/results/${run}" >/dev/null

    echo "Started eval-${run} (model: ${model}, task: ${task})"
    echo "  follow:  docker logs -f eval-${run}"
    echo "  results: ${RESULTS_DIR}/${run}/   (scores: eval-run results ${run})"
    echo "  cleanup: docker rm eval-${run}   (after it exits)"

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/eval-run
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/eval-run | cut -d' ' -f1"
    expect: "06c59c9aa8e3e5dd5f61bd983b5bfe7a656f2e6a988afa35a254fef1792d8e8b"
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
  trailing newline). It is shown indented by 4 spaces below; the
  file itself has no leading indentation:

    """Minimal OpenAI-compatible stand-in for `eval-run selftest`.

    Answers every chat completion with one fixed reply, so the whole lm_eval
    pipeline (gated dataset download, request/response handling, scoring,
    result files) can be exercised without touching Framework's GPU. Listens
    on 127.0.0.1 only, inside the selftest container.
    """

    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    MODEL = "selftest-mock"
    REPLY = "Let me think step by step. The answer is (A)."
    PORT = 18080


    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/") == "/v1/models":
                self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path.rstrip("/") != "/v1/chat/completions":
                self._send(404, {"error": "not found"})
                return
            self._send(200, {
                "id": "selftest",
                "object": "chat.completion",
                "model": MODEL,
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": REPLY},
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })

        def log_message(self, *args):
            pass


    if __name__ == "__main__":
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/mock_openai.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/mock_openai.py | cut -d' ' -f1"
    expect: "fe73688662c0359d88bcc6132522ba04a60b486647a80f3901d1daf3b395e0b9"
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
  trailing newline), then run chmod 0755 on it. It is shown indented by 4 spaces below; the
  file itself has no leading indentation:

    #!/bin/sh
    # eval-runner self-test, run inside the eval-runner image by
    # `eval-run selftest`. Starts mock_openai.py on 127.0.0.1:18080 and runs
    # both tasks at --limit 2 against it, with the same lm_eval flags as a
    # real run. That checks the gated GPQA download (HF_TOKEN), IFEval's nltk
    # data, request/response handling, scoring and result files -- without
    # Framework or its GPU. Scores are meaningless (canned replies); only
    # completion and file shape are checked, by summarize.py --check.
    set -eu

    out="/results/_selftest/${SELFTEST_RUN:?SELFTEST_RUN must be set}"

    python /opt/eval-runner/mock_openai.py &
    mock_pid=$!
    trap 'kill "$mock_pid" 2>/dev/null || true' EXIT

    i=0
    until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18080/v1/models', timeout=1)" 2>/dev/null; do
      i=$((i + 1))
      if [ "$i" -ge 50 ]; then
        echo "selftest FAILED: mock server did not start" >&2
        exit 1
      fi
      sleep 0.2
    done

    OPENAI_API_KEY=selftest lm_eval run \
      --model local-chat-completions \
      --model_args "base_url=http://127.0.0.1:18080/v1/chat/completions,model=selftest-mock,num_concurrent=1,tokenized_requests=False,timeout=60" \
      --tasks gpqa_diamond_cot_zeroshot,ifeval --apply_chat_template --log_samples \
      --gen_kwargs max_gen_toks=8192 --limit 2 \
      --output_path "$out"

    python /opt/eval-runner/summarize.py --check "$out"

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/selftest.sh
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running docker, the script, or any deploy"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/selftest.sh | cut -d' ' -f1"
    expect: "02f46f5a2bfe47aa3db2e2a36e4d4a9a9c46f701e2ef694b2133851b2a38132d"
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
  trailing newline). It is shown indented by 4 spaces below; the
  file itself has no leading indentation:

    """Print headline GPQA/IFEval numbers for eval-run result directories.

    With no arguments, summarises every run directory under /results except
    those starting with "_" (selftest output). With --check, exits non-zero
    unless every given directory holds results for both tasks with numeric
    headline metrics -- `eval-run selftest` uses this as its pass/fail.
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


    def load(run_dir):
        """Map task -> (metrics, effective sample count), newest file wins."""
        found = {}
        pattern = os.path.join(run_dir, "**", "results_*.json")
        for path in sorted(glob.glob(pattern, recursive=True)):
            with open(path) as fh:
                data = json.load(fh)
            for task, metrics in data.get("results", {}).items():
                if task in HEADLINE:
                    n = data.get("n-samples", {}).get(task, {}).get("effective")
                    found[task] = (metrics, n)
        return found


    def describe(run_dir, check):
        """Return (line, ok) for one run directory."""
        name = os.path.basename(os.path.normpath(run_dir))
        found = load(run_dir)
        if not found:
            return f"{name}: no results yet (still running, or failed)", False
        ok = True
        parts = []
        for task, columns in HEADLINE.items():
            if task not in found:
                ok = False if check else ok
                continue
            metrics, n = found[task]
            for label, key in columns:
                value = metrics.get(key)
                if isinstance(value, (int, float)):
                    parts.append(f"{label} {value * 100:.2f}%")
                else:
                    parts.append(f"{label} ?")
                    ok = False
            parts.append(f"n={n}")
        return f"{name}: " + ", ".join(parts), ok


    def main():
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--check", action="store_true")
        parser.add_argument("dirs", nargs="*")
        args = parser.parse_args()

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
                print("selftest FAILED: missing task or non-numeric headline metric", file=sys.stderr)
                return 1
            print("selftest OK")
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
    expect: "064dae1c31b873cc674b18ecf19941ff09d55aa82a8b24ccdafa0afd9928d878"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/eval-runner/summarize.py && echo OK"
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
            - selftest.sh
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

        # Runs both tasks at --limit 2 against a stand-in server inside the
        # image -- no Framework, no GPU. Proves the gated GPQA download, IFEval's
        # nltk data, scoring and result files on every deploy.
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
            msg: "{{ eval_runner_selftest.stdout_lines[-3:] }}"

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
    cmd: "tail -n 103 terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml | sha256sum | cut -d' ' -f1"
    expect: "0fad427b77aa8583341d333d3e738b7514b96c1eb6db78ae560cffa94c0334b9"
    critical: true
  - id: append-only
    cmd: "git diff --numstat stable -- terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    expect: "104\t0\tterraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
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
    expect: "6\t0\tterraform/lxc/stacks/ai-services-stack/stack.yaml"
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
- `Show eval-runner self-test summary` ends with `selftest OK`.

The self-test never touches Framework.

## Using it

```bash
ssh root@192.168.50.11
eval-run selftest              # ~15 s once datasets are cached; no GPU
eval-run results               # headline scores for every real run
eval-run gpqa --pilot          # 40 questions against Framework: GPU for ~1-2 h
eval-run gpqa                  # full GPQA diamond (198): many hours
eval-run ifeval                # full IFEval (541)
docker ps --filter name=^eval- # what's running (one real run at a time, enforced)
```

**Before starting any real run:**
- Check nothing else is using Framework: `/slots`, CyberSecEval jobs, or
  deep-research. A second client roughly halves per-request speed.
- With GLM-5.3-Flash's reasoning at `high`, single IFEval answers have run
  past 6k tokens.

**Results and cleanup:**
- Results go to `/srv/eval-runner/results/<model>-<task>[-pilot]-<UTC>/`.
  The run name includes the model id, so models never collide.
- Remove a finished container with `docker rm eval-<run>`.
- Record headline numbers in `docs/framework/eval-battery-phase2-plan.md`'s
  Phase 1 table, as before.
- Before trusting any score, open `samples_*.jsonl` and check the
  responses are real answers. Treat a 0 or near-0 score as an
  infrastructure bug until shown otherwise.

## Out of scope / follow-ups

- **RepoBench, BFCL and AgentBench.** Their harnesses live on garuda, or
  lived on the deleted `ai-stack` LXC (VMID 116), and aren't packaged
  here. lm_eval does ship a `longbench_repobench-p` task, already used
  once for Qwen3.8 (`results/qwen38-repobench-p*` on framework). That is
  a different RepoBench variant from the eval-battery table's custom
  RepoBench.
- **Running from the CyberSecEval panel.** lm_eval jobs could later become
  another job type in `cse-panel-stack`.
- **Results to Nextcloud.** Results stay local on the CT (tens of MB per
  full run; 16 GB rootfs). The GPQA terms mean sample files must not be
  shared publicly.
