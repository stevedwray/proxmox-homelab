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
