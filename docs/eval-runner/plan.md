# eval-runner: GPQA/IFEval from ai-services-stack

Status: **planned, no steps run yet (2026-10-01).** See `README.md` for
progress and hand-backs.

## Goal

Run the lm_eval-based tests from the eval battery
(`docs/framework/eval-battery-phase2-plan.md`): GPQA (diamond, CoT
zero-shot) and IFEval. They run from `ai-services-stack` against whatever
model Framework's llama-server is serving on `:8080`, instead of on
`framework` itself or garuda.

## Decisions (resolved with the operator, 2026-10-01)

- **Host: `ai-services-stack`, not a new LXC.** A GPQA run occupies
  Framework anyway, so nobody is using the local-AI services at the same
  time and isolation buys nothing. The CT already sits in `ai_seg`. It is
  2 cores, 6 GB RAM, 16 GB rootfs and 24 GB Docker storage. lm_eval needs
  about 1–2 GB of RAM and a few GB of disk.
- **No model switching.** The runner is a client of whatever llama-server
  serves. `eval-run` reads the model id from `/v1/models`. There is no
  Ollama warm/unload logic, which was the only reason the old
  `gpqa-ifeval-battery.sh` had to run on `framework`.
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
  venv that produced every number in the eval-battery doc. Every run also
  passes `--apply_chat_template --log_samples --gen_kwargs
  max_gen_toks=8192` (Bug 6), and the pilot size is `--limit 40`.
  `num_concurrent` defaults to 1 as before; `--concurrency N` is opt-in.
- **Request timeout raised to 3600 s.** lm_eval's API client defaults to
  `timeout=300`. A reasoning model at about 18 tok/s needs about 7.5 min
  for an 8192-token answer, so the default would cut it off and retry.
- **`HF_TOKEN` goes in `shared/external-apis`** in OpenBao, next to the
  other third-party API keys. GPQA's dataset (`Idavidrein/gpqa`) is gated.
  Framework's API key is not new: the playbook already receives it as
  `LLM_GPU_STACK_API_KEY` (`services/llm-gpu`), the same key OpenWebUI
  uses.

## Facts checked (2026-10-01)

- **Network:** `ai_seg → framework:8080,11434` is already allowed
  (`ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml`). So is
  zone-wide `ai_seg → !192.168.0.0/16:443`, which covers PyPI and Hugging
  Face (`mikrotik-firewall-ai-services-stack.yml` header). No firewall
  change is needed.
- **Build pattern:** matches deep-research and web-search-mcp. Source is
  in `terraform/lxc/ansible/files/<name>/`, copied by the playbook and
  built on the CT.
- **`OPENAI_API_KEY` name clash:** `shared/external-apis` contains a real
  `OPENAI_API_KEY`, and lm_eval reads that variable name. The runner only
  ever gets an explicitly written env file
  (`/etc/eval-runner/eval-runner.env`) carrying Framework's key under that
  name, never the deploy environment.
- **Dependencies:** the pins resolve cleanly for Python 3.12 (72 packages,
  no torch, transformers or CUDA). Checked with `uv pip compile`.
- **Wrapper and stack location:** `ai-services-stack` lives on `pve-tiny`
  (`docs/ai-stacks-pve-tiny/`). Deploys use `./with-secrets-prod-tiny`,
  not `./with-secrets-prod`.
- **Gates tested:** every gate below was run against a throwaway worktree
  of `stable` with the exact content applied (all pass). A deliberately
  altered copy of `eval-run` failed its hash gate.

## Steps

Write order matters for secrets. After `eval-runner-01` lands, every
`./with-secrets*` load on this branch fails closed until the operator has
written the `HF_TOKEN` value (prose after step 01). Do not run any deploy
from this branch in between.

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
   terms.
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
  Create terraform/lxc/ansible/files/eval-runner/Dockerfile with exactly
  this content (byte for byte, including the trailing newline). It is
  shown indented by 4 spaces below; the file itself has no leading
  indentation:

    # eval-runner -- lm-evaluation-harness (GPQA, IFEval) as a thin HTTP client
    # of Framework's llama-server. Built locally on ai-services-stack by
    # deploy-ai-services-stack.yml's "Install eval-runner" play and started one
    # run at a time by /usr/local/bin/eval-run -- never a long-lived compose
    # service. See docs/eval-runner/plan.md.
    FROM python:3.12-slim

    # Pinned to the lm_eval release and API/IFEval dependency versions behind
    # every GPQA/IFEval number in docs/framework/eval-battery-phase2-plan.md,
    # so new results stay comparable with the old ones. No torch/transformers:
    # the API model path doesn't need them.
    RUN pip install --no-cache-dir \
          "lm_eval[api,ifeval]==0.4.12" \
          "datasets==5.0.1" \
          "aiohttp==3.14.3" \
          "tenacity==9.1.4" \
          "langdetect==1.0.9" \
          "immutabledict==4.3.1" \
          "nltk==3.10.1" \
        && python -c "import nltk; nltk.download('punkt_tab', quiet=True)"

    WORKDIR /results
    ENTRYPOINT ["lm_eval"]

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/Dockerfile
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing any pinned version"
    - "Running docker build or any docker command"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/Dockerfile | cut -d' ' -f1"
    expect: "542fdf7e1d3dfbcde5d528c44f7ab95e0ea0c5cd525c216c144ae6315795c4fb"
    critical: true
```

### eval-runner-03-eval-run-script

```yaml
id: eval-runner-03-eval-run-script
title: Add the eval-run launcher script
depends_on: []

change: |
  Create terraform/lxc/ansible/files/eval-runner/eval-run with exactly this
  content (byte for byte, including the trailing newline), then run
  chmod 0755 on it. It is shown indented by 4 spaces below; the file
  itself has no leading indentation:

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

    Starts one detached container named eval-<run> and prints how to follow it.
      --pilot          run 40 examples (--limit 40) instead of the full task
      --concurrency N  parallel requests to llama-server (default 1, which is
                       what every historical result used)
    USAGE
    }

    [[ $# -ge 1 ]] || { usage >&2; exit 2; }
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
      -v eval-runner-hf-cache:/root/.cache/huggingface \
      "$IMAGE" run \
      --model local-chat-completions \
      --model_args "base_url=${LLM_BASE_URL}/v1/chat/completions,model=${model},num_concurrent=${concurrency},tokenized_requests=False,timeout=3600" \
      --tasks "$task" --apply_chat_template --log_samples \
      --gen_kwargs max_gen_toks=8192 \
      "${limit_args[@]}" \
      --output_path "/results/${run}" >/dev/null

    echo "Started eval-${run} (model: ${model}, task: ${task})"
    echo "  follow:  docker logs -f eval-${run}"
    echo "  results: ${RESULTS_DIR}/${run}/"
    echo "  cleanup: docker rm eval-${run}   (after it exits)"

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/eval-runner/eval-run
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the script"

gates:
  - id: exact-content
    cmd: "sha256sum terraform/lxc/ansible/files/eval-runner/eval-run | cut -d' ' -f1"
    expect: "dfc3a4705eab249a40119e8b32e8c3cb5748628b4167d73a42032cd6f554c36f"
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

### eval-runner-04-playbook-play

```yaml
id: eval-runner-04-playbook-play
title: Append the eval-runner play to deploy-ai-services-stack.yml
depends_on:
  - eval-runner-02-dockerfile
  - eval-runner-03-eval-run-script

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
        - name: Create eval-runner build, config and results directories
          ansible.builtin.file:
            path: "{{ item.path }}"
            state: directory
            mode: "{{ item.mode }}"
          loop:
            - { path: "{{ eval_runner_build_dir }}", mode: "0750" }
            - { path: /etc/eval-runner, mode: "0700" }
            - { path: /srv/eval-runner/results, mode: "0755" }

        - name: Copy eval-runner Dockerfile
          ansible.builtin.copy:
            src: "{{ eval_runner_source_dir }}/Dockerfile"
            dest: "{{ eval_runner_build_dir }}/Dockerfile"
            mode: "0644"

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
    cmd: "tail -n 65 terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml | sha256sum | cut -d' ' -f1"
    expect: "2b32c4ce369097b78f8136125e1e8eac90b34252b002bb8ff28dc9723ae299b8"
    critical: true
  - id: append-only
    cmd: "git diff --numstat stable -- terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
    expect: "66\t0\tterraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml"
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

### Operator: deploy to pve-tiny

This changes an Ansible play, so validation runs directly on `pve-tiny`
under the production approval flow (Preflight → approval →
`TASK_APPROVAL`). It needs steps 01–04 and the HF_TOKEN write.

The redeploy re-runs the whole ai-services play. Compose uses
`build: always`, so OpenWebUI and deep-research restart briefly. Don't
deploy while a deep-research job is running.

```bash
export TASK_APPROVAL=eval-runner-deploy
./with-secrets-prod-tiny scripts/provision.sh --stack ai-services-stack
```

The new play's last task prints `Framework /v1/models returned HTTP 200`
when Framework is serving. Anything else is not fatal to the deploy, but
the smoke test below will fail until it's 200.

### Operator: smoke test

From your own terminal (`ai-services-stack` is `192.168.50.11`):

```bash
ssh root@192.168.50.11 'eval-run ifeval --pilot'
ssh root@192.168.50.11 'docker logs -f eval-<run printed above>'
```

Pass: the container exits 0, and the log ends with a results table
containing `prompt_level_strict_acc`. `/srv/eval-runner/results/<run>/`
then holds a `results_*.json` and `samples_*.jsonl`. Repeat with
`eval-run gpqa --pilot`; this is the step that proves the HF token and
gated dataset work. Clean up with `docker rm eval-<run>`.

Before trusting any score, open the `samples_*.jsonl` and check that the
responses are real answers, not empty or truncated. Treat a 0 or
near-0 score as an infrastructure bug until shown otherwise (eval-battery
Robustness checklist).

## Using it

```bash
ssh root@192.168.50.11
eval-run gpqa --pilot          # 40 questions; about an hour on a ~18 tok/s model
eval-run gpqa                  # full GPQA diamond (198); many hours
eval-run ifeval                # full IFEval (541)
docker ps --filter name=^eval- # what's running (one at a time, enforced)
ls /srv/eval-runner/results/   # one dir per run: <model>-<task>[-pilot]-<UTC stamp>
```

The run name includes the model id that llama-server reports, so results
from different models never overwrite each other. Record headline numbers
in `docs/framework/eval-battery-phase2-plan.md`'s Phase 1 table, as
before.

## Out of scope / follow-ups

- **RepoBench and BFCL.** Their scripts lived on the deleted `ai-stack`
  LXC (VMID 116) and on garuda, and aren't packaged here. Recover and add
  them to this image in a later plan.
- **Running from the CyberSecEval panel.** lm_eval jobs could later become
  another job type in `cse-panel-stack` (queue, UI, Nextcloud push). Not
  needed to get numbers.
- **Results to Nextcloud.** Results stay local on the CT for now (small:
  tens of MB per full run). The CT's rootfs is 16 GB.
