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
