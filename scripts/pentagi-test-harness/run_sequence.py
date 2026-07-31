#!/usr/bin/env python3
"""Autonomous PentAGI test-harness runner.

Runs a sequence of PentAGI flows against harness-target, varying the
custom llama.cpp stack's model/sampling config between runs (gpt-oss-120b
vs Laguna S 2.1 as the adviser role, plus Qwen3.6's own ctx-size/
reasoning-budget). Designed to run unattended on the pentagi-stack LXC,
independent of any interactive session -- see README.md.

Usage:
  python3 run_sequence.py                  # run the full sequence
  python3 run_sequence.py --only 1         # run just one config, by id
  python3 run_sequence.py --dry-run        # print planned actions, no changes
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "test_sequence.json"
# This script is deployed standalone (e.g. to /opt/pentagi-test-harness on
# the pentagi-stack LXC), not necessarily inside a checkout of this repo --
# write results locally next to the script, then sync them back into
# docs/pentagi-stack/artifacts/harness-runs/ in the repo as a separate step.
RESULTS_DIR = SCRIPT_DIR / "results"

GRAPHQL_CREATE_FLOW = """
mutation($provider: String!, $input: String!) {
  createFlow(modelProvider: $provider, input: $input) { id }
}
"""

GRAPHQL_TASKS = """
query($flowId: ID!) {
  tasks(flowId: $flowId) {
    id
    status
    subtasks { id status title }
  }
}
"""


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def load_config(config_path=None):
    with open(config_path or CONFIG_PATH) as f:
        return json.load(f)


def ssh_framework(cfg, remote_cmd, use_sudo=False):
    host = cfg["framework"]["host"]
    user = cfg["framework"]["user"]
    cmd = f"sudo {remote_cmd}" if use_sudo else remote_cmd
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"{user}@{host}", cmd],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh framework command failed: {remote_cmd}\n{result.stderr}")
    return result.stdout


def http_get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read()


def http_post_json(url, payload, timeout=15, cookie_jar=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    if cookie_jar:
        req.add_header("Cookie", cookie_jar)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cookies = resp.headers.get_all("Set-Cookie")
            return resp.status, json.loads(resp.read()), cookies
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), None


# --- llama.cpp router / models-preset.ini -----------------------------------

def update_models_preset(cfg, run):
    """Rewrite the Qwen3.6 and adviser sections of models-preset.ini on framework."""
    preset_path = cfg["framework"]["models_preset_path"]
    content = ssh_framework(cfg, f"cat {preset_path}")

    qwen_section = (
        "[Qwen3.6-35B-A3B-UD-Q4_K_M]\n"
        f"reasoning-budget = {run['qwen_reasoning_budget']}\n"
        "reasoning-budget-message = Stop thinking now and give your final answer as a tool call.\n"
        f"ctx-size = {run['qwen_ctx_size']}\n"
    )
    content = re.sub(
        r"\[Qwen3\.6-35B-A3B-UD-Q4_K_M\]\n(?:[^\[]*\n?)*",
        qwen_section + "\n", content,
    )

    # Remove any existing gpt-oss / Laguna sections, then add back only the
    # one this run actually uses.
    content = re.sub(r"\[gpt-oss-120b\]\n(?:[^\[]*\n?)*", "", content)
    content = re.sub(
        r"\[Laguna-S-2\.1-UD-Q4_K_M-00001-of-00003\]\n(?:[^\[]*\n?)*", "", content,
    )
    adviser_section = f"[{run['adviser_model']}]\nctx-size = {run['adviser_ctx_size']}\n"
    content = content.rstrip() + "\n\n" + adviser_section

    tmp_remote = "/tmp/models-preset.ini.new"
    escaped = content.replace("'", "'\\''")
    ssh_framework(cfg, f"cat > {tmp_remote} << 'PRESET_EOF'\n{content}\nPRESET_EOF")
    ssh_framework(cfg, f"cp {tmp_remote} {preset_path}", use_sudo=True)
    log(f"models-preset.ini updated: qwen ctx={run['qwen_ctx_size']} rb={run['qwen_reasoning_budget']}, "
        f"adviser={run['adviser_model']} ctx={run['adviser_ctx_size']}")


def reload_router(cfg):
    url = cfg["framework"]["router_url"] + "/v1/models?reload=1"
    status, _ = http_get(url)
    log(f"router reload: HTTP {status}")


def unload_model(cfg, model_id):
    url = cfg["framework"]["router_url"] + "/models/unload"
    data = json.dumps({"model": model_id}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            log(f"unload {model_id}: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        log(f"unload {model_id}: HTTP {e.code} (may not have been loaded)")


def free_ollama_if_needed(cfg):
    """Defensive: stop any Ollama-resident models on framework before a run,
    mirroring the manual fix applied this session (Ollama held ~74GB
    indefinitely and caused an OOM loading Laguna alone)."""
    out = ssh_framework(cfg, "curl -s http://localhost:11434/api/ps")
    try:
        models = json.loads(out).get("models", [])
    except json.JSONDecodeError:
        models = []
    for m in models:
        name = m["name"]
        ssh_framework(cfg, f"curl -s http://localhost:11434/api/generate "
                            f"-d '{{\"model\":\"{name}\",\"keep_alive\":0}}' -o /dev/null")
        log(f"stopped Ollama-resident model: {name}")
    if models:
        time.sleep(3)


def check_memory(cfg, min_available_gb=30):
    out = ssh_framework(cfg, "free -m | awk '/^Mem:/{print $7}'")
    available_mb = int(out.strip())
    available_gb = available_mb / 1024
    log(f"framework available memory: {available_gb:.1f}GiB")
    return available_gb >= min_available_gb


# --- custom stack's own provider config (adviser role swap) -----------------

def get_current_adviser_model(cfg):
    content = Path(cfg["custom_stack"]["provider_config_path"]).read_text()
    m = re.search(r'adviser:\s*\n\s*model:\s*"([^"]+)"', content)
    return m.group(1) if m else None


def recreate_pentagi_container(cfg):
    compose_dir = cfg["custom_stack"]["compose_dir"]
    container = cfg["custom_stack"]["pentagi_container"]
    subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate", container],
        cwd=compose_dir, check=True, capture_output=True, text=True,
    )
    log(f"{container} container recreated")
    time.sleep(10)  # let it come back up before we hit its API


def swap_adviser_model(cfg, new_model):
    path = Path(cfg["custom_stack"]["provider_config_path"])
    content = path.read_text()
    content = re.sub(
        r'(adviser:\s*\n\s*model:\s*)"[^"]+"',
        rf'\1"{new_model}"', content,
    )
    path.write_text(content)
    log(f"custom.provider.yml adviser model set to {new_model}")
    recreate_pentagi_container(cfg)


def swap_all_roles_to_model(cfg, new_model):
    """Point every PentAGI role at a single model (e.g. to test a
    candidate model standalone, with no other model in the mix at all).
    Assumes every role currently shares one other model (the "default"),
    since that's this stack's actual layout -- replaces every model
    reference except any already pointing at new_model itself."""
    path = Path(cfg["custom_stack"]["provider_config_path"])
    content = path.read_text()
    content = re.sub(
        r'model:\s*"(?!' + re.escape(new_model) + r'")[^"]+"',
        f'model: "{new_model}"', content,
    )
    path.write_text(content)
    log(f"custom.provider.yml: ALL roles set to {new_model}")
    recreate_pentagi_container(cfg)


# --- PentAGI API --------------------------------------------------------

def pentagi_login(cfg):
    base = cfg["pentagi"]["base_url"]
    password = os.environ.get(cfg["pentagi"]["password_env_var"])
    if not password:
        raise RuntimeError(
            f"Set {cfg['pentagi']['password_env_var']} in the environment before running."
        )
    status, body, cookies = http_post_json(
        base + "/api/v1/auth/login",
        {"mail": cfg["pentagi"]["email"], "password": password},
    )
    if status != 200:
        raise RuntimeError(f"PentAGI login failed: HTTP {status} {body}")
    cookie_header = "; ".join(c.split(";")[0] for c in (cookies or []))
    log("PentAGI login succeeded")
    return cookie_header


def create_flow(cfg, cookie):
    base = cfg["pentagi"]["base_url"]
    status, body, _ = http_post_json(
        base + "/api/v1/graphql",
        {"query": GRAPHQL_CREATE_FLOW, "variables": {
            "provider": "custom", "input": cfg["target"]["prompt"],
        }},
        timeout=300,  # createFlow triggers real plan generation, not a quick API call
        cookie_jar=cookie,
    )
    if status != 200 or "errors" in body:
        raise RuntimeError(f"createFlow failed: HTTP {status} {body}")
    flow_id = body["data"]["createFlow"]["id"]
    log(f"created flow {flow_id}")
    return flow_id


def poll_flow(cfg, cookie, flow_id):
    base = cfg["pentagi"]["base_url"]
    interval = cfg["poll_interval_start_seconds"]
    max_interval = cfg["poll_interval_max_seconds"]
    timeout_s = cfg["watchdog_timeout_minutes"] * 60
    start = time.time()

    while time.time() - start < timeout_s:
        status, body, _ = http_post_json(
            base + "/api/v1/graphql",
            {"query": GRAPHQL_TASKS, "variables": {"flowId": flow_id}},
            cookie_jar=cookie,
        )
        tasks = body.get("data", {}).get("tasks", []) if status == 200 else []
        if tasks:
            task_status = tasks[0]["status"]
            log(f"flow {flow_id}: task status = {task_status}")
            if task_status in ("finished", "failed"):
                return tasks, time.time() - start
        time.sleep(interval)
        interval = min(interval * 1.5, max_interval)

    log(f"flow {flow_id}: watchdog timeout after {cfg['watchdog_timeout_minutes']} minutes, stopping")
    http_post_json(
        base + "/api/v1/graphql",
        {"query": "mutation($id: ID!) { stopFlow(flowId: $id) }",
         "variables": {"id": flow_id}},
        cookie_jar=cookie,
    )
    return tasks if 'tasks' in dir() else [], time.time() - start


# --- Result logging ------------------------------------------------------

def gather_toolcall_summary(flow_id):
    query = (
        f"select subtask_id, count(*) from toolcalls "
        f"where flow_id={flow_id} group by subtask_id order by subtask_id;"
    )
    result = subprocess.run(
        ["docker", "exec", "pgvector", "psql", "-U", "postgres", "-d", "pentagidb", "-c", query],
        capture_output=True, text=True,
    )
    return result.stdout


def write_result_file(run, flow_id, tasks, elapsed_s):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{run['id']}-{run['label']}.md"
    toolcall_summary = gather_toolcall_summary(flow_id)

    lines = [
        f"# Run {run['id']}: {run['label']}",
        "",
        f"- Flow ID: {flow_id}",
        f"- Adviser model: {run['adviser_model']} (ctx={run['adviser_ctx_size']})",
        f"- Qwen3.6 ctx-size: {run['qwen_ctx_size']}, reasoning-budget: {run['qwen_reasoning_budget']}",
        f"- Wall-clock duration: {elapsed_s / 60:.1f} minutes",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Final task/subtask status",
        "",
    ]
    for task in tasks:
        lines.append(f"- Task {task['id']}: {task['status']}")
        for st in task.get("subtasks", []):
            lines.append(f"  - Subtask {st['id']} ({st['status']}): {st['title']}")
    lines += ["", "## Toolcall counts per subtask", "", "```", toolcall_summary.strip(), "```"]

    out_path.write_text("\n".join(lines) + "\n")
    log(f"wrote result file: {out_path}")


# --- Main sequence --------------------------------------------------------

def run_one(cfg, run, previous_adviser_model):
    log(f"=== Starting run {run['id']}: {run['label']} ===")

    all_roles = run.get("all_roles", False)
    is_laguna = "laguna" in run["adviser_model"].lower()

    # The memory gate only matters when we're about to make a NEW model
    # resident. An all_roles run never does that here -- Laguna is
    # already loaded, and the only change is unloading Qwen3.6 (which
    # can only free memory, never risk OOM) -- so skip the pre-check
    # for that case; checking before the free would see the wrong state.
    if is_laguna and not all_roles:
        free_ollama_if_needed(cfg)
        if not check_memory(cfg, min_available_gb=30):
            log(f"SKIPPING run {run['id']}: insufficient free memory for Laguna, not risking OOM")
            return None

    if all_roles:
        # Every role (primary_agent/pentester/coder/etc, not just adviser)
        # moves to this model -- the shared default model (Qwen3.6) is no
        # longer used by anything, so free it. Ctx-size/reasoning-budget
        # for the target model are assumed unchanged from the previous
        # run (no models-preset edit, no router reload -- avoids an
        # unnecessary reload of an already-loaded model).
        unload_model(cfg, "Qwen3.6-35B-A3B-UD-Q4_K_M")
        swap_all_roles_to_model(cfg, run["adviser_model"])
    else:
        adviser_changed = run["adviser_model"] != previous_adviser_model
        if adviser_changed:
            if previous_adviser_model:
                unload_model(cfg, previous_adviser_model)
            swap_adviser_model(cfg, run["adviser_model"])
        update_models_preset(cfg, run)
        reload_router(cfg)

    cookie = pentagi_login(cfg)
    flow_id = create_flow(cfg, cookie)
    tasks, elapsed = poll_flow(cfg, cookie, flow_id)
    write_result_file(run, flow_id, tasks, elapsed)
    log(f"=== Finished run {run['id']}: {run['label']} ===")
    return run["adviser_model"]


def resume_first_run(cfg, runs):
    """The first run in the sequence was already started manually (config
    already applied, flow already created) -- just poll it to completion
    and log the result, then let the normal loop continue from run 2
    onward. Used when a flow was hand-started before the unattended
    sequence was launched, so we don't waste a loaded model re-doing
    work that's already in progress."""
    run = runs[0]
    flow_id = int(os.environ["RESUME_FLOW_ID"])
    log(f"=== Resuming run {run['id']}: {run['label']} (flow {flow_id}, already in progress) ===")
    cookie = pentagi_login(cfg)
    tasks, elapsed = poll_flow(cfg, cookie, flow_id)
    write_result_file(run, flow_id, tasks, elapsed)
    log(f"=== Finished resumed run {run['id']}: {run['label']} ===")
    return run["adviser_model"]


def run_all(cfg, runs, previous_adviser_model):
    remaining = list(runs)
    if os.environ.get("RESUME_FLOW_ID"):
        try:
            result = resume_first_run(cfg, remaining)
            if result:
                previous_adviser_model = result
        except Exception as e:
            log(f"resume of run {remaining[0]['id']} FAILED: {e}")
        remaining = remaining[1:]

    for run in remaining:
        try:
            result = run_one(cfg, run, previous_adviser_model)
            if result:
                previous_adviser_model = result
        except Exception as e:
            log(f"run {run['id']} ({run['label']}) FAILED: {e}")
            continue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, help="Run only this run id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", type=Path, help="Path to an alternate test_sequence.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    runs = cfg["runs"]
    if args.only:
        runs = [r for r in runs if r["id"] == args.only]
        if not runs:
            sys.exit(f"No run with id {args.only}")

    if args.dry_run:
        for r in runs:
            print(json.dumps(r, indent=2))
        return

    previous_adviser_model = get_current_adviser_model(cfg)
    log(f"starting sequence, current adviser model = {previous_adviser_model}")

    run_all(cfg, runs, previous_adviser_model)
    log("sequence complete")


if __name__ == "__main__":
    main()
