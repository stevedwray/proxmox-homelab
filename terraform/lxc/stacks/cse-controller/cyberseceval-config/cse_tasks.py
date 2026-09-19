"""Celery worker for cse-controller -- runs on cse-controller itself (see
docker-compose.yml's `worker` service), consuming jobs submitted by
cse-panel-stack's panel-web across the cse_seg -> mgmt_seg:6379 firewall
rule. One task, run_benchmark, covers every benchmark proven in the
2026-09-19 small-batch run (see
docs/cyberseceval-implementation/current-state.md) -- the same CLI shapes
as ansible/00-initial-setup/cse-small-batch-run.yml's run-batch.sh,
parameterized instead of hardcoded per-benchmark.
"""
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from celery import Celery

BROKER_URL = os.environ["CELERY_BROKER_URL"]
RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

app = Celery("cse_tasks", broker=BROKER_URL, backend=RESULT_BACKEND)

REPO_DIR = Path("/srv/cyberseceval/repo/PurpleLlama")
VENV_PY = Path("/srv/cyberseceval/.venv/bin/python3")
RUNS_DIR = Path("/srv/cyberseceval/runs")

# Framework's llama-server, matching the exact spec proven in Phase 2
# (docs/cyberseceval-implementation/current-state.md) and reused by
# cse-small-batch-run.yml.
MUT_SPEC = (
    "OPENAI::/models/qwen3.8-flash-next-q4/UD-Q4_K_XL/"
    "Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf::not-needed::"
    "http://framework.gibbsgreatly.xyz:8080/v1"
)


def _judge_spec() -> str:
    key = os.environ["OPENAI_API_KEY"]
    return f"OPENAI::gpt-4o-mini::{key}"


# Each entry: the exact argv (minus python3/module prefix) run.py needs,
# using {run_dir} as the per-job output directory placeholder.
_BENCHMARK_COMMANDS = {
    "mitre": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=mitre",
        "--prompt-path=CybersecurityBenchmarks/datasets/mitre/mitre_benchmark_100_per_category_with_augmentation.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}", f"--expansion-llm={_judge_spec()}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "mitre-frr": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=mitre-frr",
        "--prompt-path=CybersecurityBenchmarks/datasets/mitre_frr/mitre_frr.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "prompt-injection": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=prompt-injection",
        "--prompt-path=CybersecurityBenchmarks/datasets/prompt_injection/prompt_injection.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "interpreter": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=interpreter",
        "--prompt-path=CybersecurityBenchmarks/datasets/interpreter/interpreter.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "instruct": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=instruct",
        "--prompt-path=CybersecurityBenchmarks/datasets/instruct/instruct-v2.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "autocomplete": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=autocomplete",
        "--prompt-path=CybersecurityBenchmarks/datasets/autocomplete/autocomplete.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "malware_analysis": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=malware_analysis",
        "--prompt-path=CybersecurityBenchmarks/datasets/crwd_meta/malware_analysis/questions.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "threat_intel_reasoning": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=threat_intel_reasoning",
        "--prompt-path=CybersecurityBenchmarks/datasets/crwd_meta/threat_intel_reasoning/report_questions.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        "--input-modality=text",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "multiturn-phishing": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=multiturn-phishing",
        "--prompt-path=CybersecurityBenchmarks/datasets/spear_phishing/multiturn_phishing_challenges.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        f"--judge-llm={MUT_SPEC}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
}


def _run_autonomous_uplift(run_dir: Path, shots: int) -> dict:
    gen_cmd = [
        str(VENV_PY), "-m", "CybersecurityBenchmarks.datasets.autonomous_uplift.test_case_generator",
        "--ssh-key-file=/srv/cyberseceval/config/cse-kali-agent-key",
        "--ssh-username=kali",
        "--cyber-range-file=/srv/cyberseceval/config/cyber_range_pairs.json",
        "--system-prompt-file=CybersecurityBenchmarks/datasets/autonomous_uplift/in/system_prompt.txt",
        f"--out-file={run_dir}/prompts.json",
        f"--shots-per-run={shots}", "--runs-per-range=1",
    ]
    gen = subprocess.run(gen_cmd, cwd=REPO_DIR, capture_output=True, text=True)
    if gen.returncode != 0:
        return {"rc": gen.returncode, "stage": "generate", "log": gen.stdout + gen.stderr}
    attack_cmd = [
        str(VENV_PY), "-m", "CybersecurityBenchmarks.benchmark.run",
        "--benchmark=autonomous-uplift",
        f"--prompt-path={run_dir}/prompts.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}",
    ]
    attack = subprocess.run(attack_cmd, cwd=REPO_DIR, capture_output=True, text=True)
    return {"rc": attack.returncode, "stage": "attack", "log": attack.stdout + attack.stderr}


@app.task(name="cse_tasks.run_benchmark")
def run_benchmark(benchmark: str, num_test_cases: int = 2, submitted_by: str = "unknown") -> dict:
    job_id = run_benchmark.request.id
    run_dir = RUNS_DIR / f"panel-{job_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        f'{{"benchmark": "{benchmark}", "num_test_cases": {num_test_cases}, '
        f'"submitted_by": "{submitted_by}", "started_at": "{datetime.now(timezone.utc).isoformat()}"}}'
    )

    if benchmark == "autonomous-uplift":
        result = _run_autonomous_uplift(run_dir, shots=num_test_cases)
    else:
        if benchmark not in _BENCHMARK_COMMANDS:
            return {"rc": 1, "error": f"unknown benchmark '{benchmark}'"}
        argv = [str(VENV_PY)] + _BENCHMARK_COMMANDS[benchmark](str(run_dir), num_test_cases)
        proc = subprocess.run(argv, cwd=REPO_DIR, capture_output=True, text=True)
        (run_dir / "run.log").write_text(proc.stdout + proc.stderr)
        result = {"rc": proc.returncode, "log_path": str(run_dir / "run.log")}

    result["run_dir"] = str(run_dir)
    return result
