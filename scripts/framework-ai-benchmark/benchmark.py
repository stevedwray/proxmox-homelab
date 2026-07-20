#!/usr/bin/env python3
"""Autonomous quality/performance benchmark for the Framework LLM runtimes.

Standard-library only by design: the script can run from the rebuilt Framework
host without a virtual environment or package installation.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
import platform
import re
import resource
import signal
import socket
import statistics
# Fixed argv only; generated code passes a strict AST allowlist and rlimits.
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


OPENAI_ENDPOINTS = {
    "llamacpp": os.getenv("FRAMEWORK_BENCH_LLAMACPP_URL", "http://127.0.0.1:8080"),
    "lmstudio": os.getenv("FRAMEWORK_BENCH_LMSTUDIO_URL", "http://127.0.0.1:8090"),
}
OLLAMA_URL = os.getenv("FRAMEWORK_BENCH_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_TAGS_PATH = "/api/tags"
SUITES = ("chat", "story", "code_generation", "code_refactoring", "security")
LMSTUDIO_SERVICE = "lmstudio.service"
LMSTUDIO_TIMER = "lmstudio-healthcheck.timer"
LLAMACPP_CONTAINER = "llamacpp-router"
OLLAMA_CONTAINER = "ollama"
DEFAULT_RESULTS_ROOT = Path("/storage/artifacts/framework-ai-benchmarks")
RUN_NAME_RE = re.compile(r"^\d{8}T\d{6}$")


@dataclasses.dataclass(frozen=True)
class Task:
    suite: str
    name: str
    system: str
    prompt: str
    max_tokens: int
    temperature: float
    grader: Callable[[str], dict[str, Any]]


def check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def grade_checks(checks: list[dict[str, Any]], notes: str = "") -> dict[str, Any]:
    passed = sum(int(item["passed"]) for item in checks)
    return {
        "score": passed / len(checks) if checks else 0.0,
        "passed": passed == len(checks),
        "checks": checks,
        "notes": notes,
    }


def words(text: str) -> list[str]:
    return re.findall(r"\b[\w'-]+\b", text, re.UNICODE)


def bullet_count(text: str) -> int:
    return len(re.findall(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", text))


def grade_incident_chat(text: str) -> dict[str, Any]:
    lower = text.lower()
    count = len(words(text))
    return grade_checks([
        check("exactly_four_bullets", bullet_count(text) == 4, f"found {bullet_count(text)}"),
        check("within_170_words", 60 <= count <= 170, f"found {count}"),
        check("identifies_db_pool", "database" in lower and "pool" in lower),
        check("recommends_rollback", "rollback" in lower or "roll back" in lower),
        check("includes_customer_comms", "customer" in lower and any(x in lower for x in ("notify", "update", "communicat"))),
    ])


def grade_context_chat(text: str) -> dict[str, Any]:
    lower = text.lower()
    no_database = "database" not in lower or any(
        phrase in lower for phrase in ("without a database", "no database", "avoid a database", "doesn't rely on a database", "does not rely on a database")
    )
    return grade_checks([
        check("uses_project_name", "orchard" in lower),
        check("uses_language", "python" in lower),
        check("respects_no_database", no_database),
        check("mentions_json", "json" in lower),
        check("asks_one_question", text.count("?") == 1, f"found {text.count('?')} question marks"),
        check("concise", len(words(text)) <= 140, f"found {len(words(text))} words"),
    ])


def grade_reasoning_chat(text: str) -> dict[str, Any]:
    lower = text.lower()
    return grade_checks([
        check("correct_day", "thursday" in lower),
        check("correct_time", bool(re.search(r"\b(2(?::?00)?\s*pm|14[:.]00)\b", lower))),
        check("shows_duration", "90" in lower or "1.5" in lower or "one and a half" in lower),
        check("no_extra_assumption", "friday" not in lower),
        check("concise", len(words(text)) <= 100, f"found {len(words(text))} words"),
    ])


def grade_lighthouse_story(text: str) -> dict[str, Any]:
    lower = text.lower()
    count = len(words(text))
    unique_ratio = len({word.lower() for word in words(text)}) / max(1, count)
    return grade_checks([
        check("word_range", 500 <= count <= 850, f"found {count}"),
        check("contains_mara", "mara" in lower),
        check("contains_brass_key", "brass key" in lower),
        check("contains_radio_weather", "radio" in lower and any(x in lower for x in ("storm", "weather", "wind", "gale"))),
        check("ends_required_sentence", text.rstrip().endswith("The light answered.")),
        check("avoids_dream_cliche", "it was all a dream" not in lower),
        check("lexical_variety", unique_ratio >= 0.38, f"ratio {unique_ratio:.3f}"),
    ], "Constraint/lexical score only; read the saved transcript for subjective prose quality.")


def grade_colony_story(text: str) -> dict[str, Any]:
    lower = text.lower()
    count = len(words(text))
    return grade_checks([
        check("word_range", 450 <= count <= 800, f"found {count}"),
        check("second_person", len(re.findall(r"\byou\b", lower)) >= 8),
        check("three_required_images", all(x in lower for x in ("red dust", "seed vault", "cracked visor"))),
        check("no_dialogue", not bool(re.search(r'[\"“”]', text))),
        check("final_word_home", words(text)[-1].lower().rstrip(".") == "home" if words(text) else False),
        check("avoids_wakeup_cliche", "woke up" not in lower and "awoke" not in lower),
    ], "Constraint score only; read the saved transcript for subjective prose quality.")


def extract_python(text: str) -> str:
    for block in text.split("```")[1::2]:
        candidate = block.lstrip()
        if candidate.lower().startswith("python"):
            candidate = candidate[6:].lstrip(" \t\r\n")
        if any(line.lstrip().startswith("def ") for line in candidate.splitlines()):
            return candidate.strip()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("def "):
            return "\n".join(lines[index:]).strip()
    return text.strip()


ALLOWED_CALLS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
    "isinstance", "len", "list", "max", "min", "range", "reversed",
    "round", "set", "sorted", "str", "sum", "tuple", "zip",
    "TypeError", "ValueError",
}
ALLOWED_METHODS = {
    "append", "casefold", "copy", "count", "extend", "get", "isalnum",
    "items", "join", "keys", "lower", "pop", "replace", "rstrip",
    "setdefault", "sort", "split", "strip", "update", "upper", "values",
}


FORBIDDEN_AST = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef,
                 ast.With, ast.AsyncWith, ast.Global, ast.Nonlocal, ast.Delete)


def validate_top_level(tree: ast.Module) -> str | None:
    for node in tree.body:
        is_docstring = (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str))
        if not isinstance(node, ast.FunctionDef) and not is_docstring:
            return f"unsafe top-level statement: {type(node).__name__}"
    return None


def validate_ast_node(node: ast.AST, function_names: set[str]) -> str | None:
    if isinstance(node, FORBIDDEN_AST):
        return f"disallowed syntax: {type(node).__name__}"
    if isinstance(node, ast.Name) and node.id.startswith("__"):
        return f"disallowed name: {node.id}"
    if isinstance(node, ast.Attribute) and (node.attr.startswith("__") or node.attr not in ALLOWED_METHODS):
        return f"disallowed attribute: {node.attr}"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id not in ALLOWED_CALLS and node.func.id not in function_names:
            return f"disallowed call: {node.func.id}"
    return None


def validate_generated_code(code: str, required: set[str]) -> tuple[bool, str, ast.Module | None]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax error: {exc}", None
    public_functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not required.issubset(public_functions):
        return False, f"missing required function(s): {sorted(required - public_functions)}", tree
    callable_functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    top_level_error = validate_top_level(tree)
    if top_level_error:
        return False, top_level_error, tree
    for node in ast.walk(tree):
        node_error = validate_ast_node(node, callable_functions)
        if node_error:
            return False, node_error, tree
    return True, "safe AST", tree


def limit_child() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_NPROC, (8, 8))


def execute_hidden_tests(code: str, test_code: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="framework-bench-code-") as tmp:
        try:
            # Generated code has passed validate_generated_code before this call.
            run = subprocess.run(  # nosec B603
                [sys.executable, "-I", "-c", code + "\n\n" + test_code],
                cwd=tmp,
                env={"PATH": os.getenv("PATH", "/usr/bin:/bin"), "PYTHONHASHSEED": "0"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=6,
                preexec_fn=limit_child,
                check=False,
            )
            output = run.stdout[-4000:]
            return run.returncode == 0, output or f"exit={run.returncode}"
        except subprocess.TimeoutExpired:
            return False, "hidden tests timed out"


MERGE_TESTS = r'''
assert merge_intervals([]) == []
assert merge_intervals([[1, 3]]) == [[1, 3]]
assert merge_intervals([[1, 3], [2, 6], [8, 10], [10, 12]]) == [[1, 6], [8, 12]]
assert merge_intervals([[5, 7], [1, 2], [2, 4]]) == [[1, 4], [5, 7]]
source = [[5, 7], [1, 2]]
snapshot = [x[:] for x in source]
assert merge_intervals(source) == [[1, 2], [5, 7]]
assert source == snapshot
try:
    merge_intervals([[3, 1]])
except ValueError:
    pass
else:
    raise AssertionError("reversed interval must raise ValueError")
print("hidden tests passed")
'''


SLUG_TESTS = r'''
assert slugify("Hello, World!") == "hello-world"
assert slugify("  Multiple   spaces___here ") == "multiple-spaces-here"
assert slugify("Café déjà vu") == "café-déjà-vu"
assert slugify("---") == ""
assert slugify("A--B__C") == "a-b-c"
print("hidden tests passed")
'''


ORDER_TESTS = r'''
sample = [
 {"id": "a", "status": "paid", "amount": 10.5},
 {"id": "b", "status": "pending", "amount": 4},
 {"id": "c", "status": "paid", "amount": 2},
]
snapshot = [x.copy() for x in sample]
assert summarize_orders(sample) == {"paid_total": 12.5, "paid_count": 2, "pending_ids": ["b"]}
assert sample == snapshot
assert summarize_orders([]) == {"paid_total": 0, "paid_count": 0, "pending_ids": []}
try:
    summarize_orders([{"id": "x", "status": "paid"}])
except ValueError:
    pass
else:
    raise AssertionError("missing amount must raise ValueError")
print("hidden tests passed")
'''


CHUNK_TESTS = r'''
assert chunk_records([], 3) == []
assert chunk_records([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
source = [{"x": 1}, {"x": 2}]
result = chunk_records(source, 1)
assert result == [[{"x": 1}], [{"x": 2}]]
assert source == [{"x": 1}, {"x": 2}]
for bad in (0, -1, 1.5, True):
    try:
        chunk_records([1], bad)
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError(f"bad size accepted: {bad!r}")
print("hidden tests passed")
'''


def code_grader(required: set[str], tests: str, structural: Callable[[ast.Module], list[dict[str, Any]]] | None = None) -> Callable[[str], dict[str, Any]]:
    def grade(text: str) -> dict[str, Any]:
        code = extract_python(text)
        safe, detail, tree = validate_generated_code(code, required)
        checks = [check("safe_parseable_python", safe, detail)]
        if not safe or tree is None:
            return grade_checks(checks)
        test_passed, output = execute_hidden_tests(code, tests)
        checks.append(check("hidden_tests", test_passed, output))
        if structural:
            checks.extend(structural(tree))
        result = grade_checks(checks)
        result["extracted_code"] = code
        return result
    return grade


def order_structure(tree: ast.Module) -> list[dict[str, Any]]:
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    loops = sum(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree))
    return [
        check("helper_extracted", len(functions) >= 2, f"found {len(functions)} functions"),
        check("bounded_loop_count", loops <= 2, f"found {loops} loops"),
    ]


def chunk_structure(tree: ast.Module) -> list[dict[str, Any]]:
    source = ast.unparse(tree)
    return [
        check("single_public_function", sum(isinstance(x, ast.FunctionDef) for x in tree.body) == 1),
        check("clear_validation", "raise" in source and ("TypeError" in source or "ValueError" in source)),
    ]


def extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    for value in reversed(candidates):
        if "verdict" in value:
            return value
    return candidates[-1] if candidates else None


def security_grader(expected_verdict: str, expected_cwes: set[str]) -> Callable[[str], dict[str, Any]]:
    def grade(text: str) -> dict[str, Any]:
        obj = extract_json_object(text)
        if obj is None:
            return grade_checks([check("valid_json", False, "no JSON object found")])
        verdict = str(obj.get("verdict", "")).lower()
        raw_cwes = obj.get("cwes", [])
        if isinstance(raw_cwes, str):
            raw_cwes = [raw_cwes]
        cwes = {str(item).upper() for item in raw_cwes if isinstance(item, (str, int))}
        evidence = obj.get("evidence", [])
        remediation = str(obj.get("remediation", ""))
        checks = [
            check("valid_json", True),
            check("correct_verdict", verdict == expected_verdict, f"found {verdict!r}"),
        ]
        if expected_verdict == "vulnerable":
            checks.extend([
                check("expected_cwe", bool(cwes & expected_cwes), f"found {sorted(cwes)}"),
                check("has_evidence", isinstance(evidence, list) and bool(evidence)),
                check("has_remediation", len(words(remediation)) >= 4),
            ])
        else:
            checks.extend([
                check("no_false_positive_cwe", not cwes, f"found {sorted(cwes)}"),
                check("no_false_positive_evidence", evidence in ([], None, ""), f"found {evidence!r}"),
            ])
        result = grade_checks(checks)
        result["parsed_verdict"] = obj
        return result
    return grade


SECURITY_SYSTEM = """You are performing a bounded code-security review. Return exactly one JSON object and no markdown. Schema: {"verdict":"vulnerable"|"safe","cwes":["CWE-NNN"],"evidence":["specific data-flow or unsafe operation"],"remediation":"specific fix"}. A safe sample must use empty cwes and evidence arrays. Do not invent missing context."""


def build_tasks(smoke: bool) -> list[Task]:
    scale = 0.55 if smoke else 1.0

    def cap(value: int) -> int:
        return max(260, int(value * scale))
    tasks = [
        Task("chat", "incident_response", "You are a calm senior SRE. Follow all formatting constraints.",
             "A deploy at 13:05 changed payments-api database pooling. At 13:12, checkout errors rose from 0.2% to 18%. The previous release is known-good. Write exactly four bullets for the incident channel: diagnosis, immediate mitigation, verification, and customer communication. Use 60-170 words.", cap(520), 0.2, grade_incident_chat),
        Task("chat", "context_and_question", "You are a pragmatic software architect.",
             "Remember these project facts: project Orchard; Python 3.14; configuration must be JSON files; no database is allowed. Propose a compact configuration-loading approach that respects every fact, then ask exactly one clarifying question. Stay under 140 words.", cap(420), 0.2, grade_context_chat),
        Task("chat", "schedule_reasoning", "Answer precisely and show the short calculation.",
             "A maintenance starts Tuesday at 22:30. It runs for 11 hours, pauses for 27 hours, then resumes for 90 minutes. State the weekday and local time when it finishes. Use no more than 100 words.", cap(320), 0.0, grade_reasoning_chat),
        Task("story", "lighthouse", "Write polished literary speculative fiction and obey literal constraints.",
             "Write a complete 500-850 word story about lighthouse keeper Mara, a brass key, and a radio that predicts weather from lost worlds. Do not use the phrase 'it was all a dream'. The final sentence must be exactly: The light answered.", cap(1250), 0.75, grade_lighthouse_story),
        Task("story", "mars_colony", "Write vivid, coherent second-person science fiction and obey literal constraints.",
             "Write a complete 450-800 word story in second person. It must naturally include the images 'red dust', 'seed vault', and 'cracked visor'. Use no quoted dialogue and no waking-from-a-dream ending. The final word must be 'home'.", cap(1150), 0.75, grade_colony_story),
        Task("code_generation", "merge_intervals", "Return only one Python code block. Do not import anything or perform I/O.",
             "Implement merge_intervals(intervals). Input is a list of two-item integer lists. Return new sorted merged lists; overlapping or touching intervals merge. Do not mutate input. Raise ValueError when start > end. Empty input returns [].", cap(900), 0.1, code_grader({"merge_intervals"}, MERGE_TESTS)),
        Task("code_generation", "unicode_slugify", "Return only one Python code block. Do not import anything or perform I/O.",
             "Implement slugify(text). Lowercase Unicode text, retain alphanumeric Unicode characters, replace every run of whitespace, underscore, or hyphen with one hyphen, drop other punctuation, and strip edge hyphens.", cap(850), 0.1, code_grader({"slugify"}, SLUG_TESTS)),
        Task("code_refactoring", "orders", "Return only the complete replacement Python code. Do not import anything or perform I/O.",
             "Refactor the function below for clarity, with at least one well-named helper and no input mutation. Preserve output. Validate that paid orders contain amount and raise ValueError if not.\n\n```python\ndef summarize_orders(orders):\n    paid_total = 0\n    paid_count = 0\n    for order in orders:\n        if order.get('status') == 'paid':\n            paid_total += order['amount']\n            paid_count += 1\n    pending_ids = []\n    for order in orders:\n        if order.get('status') == 'pending':\n            pending_ids.append(order['id'])\n    return {'paid_total': paid_total, 'paid_count': paid_count, 'pending_ids': pending_ids}\n```", cap(1050), 0.1, code_grader({"summarize_orders"}, ORDER_TESTS, order_structure)),
        Task("code_refactoring", "chunk_records", "Return only the complete replacement Python code. Do not import anything or perform I/O.",
             "Refactor this implementation without changing the public name. Preserve order and input. Reject bool/non-integer size with TypeError and size <= 0 with ValueError.\n\n```python\ndef chunk_records(records, size):\n    result = []\n    current = []\n    index = 0\n    while index < len(records):\n        current.append(records[index])\n        if len(current) == size:\n            result.append(current)\n            current = []\n        index += 1\n    if current:\n        result.append(current)\n    return result\n```", cap(900), 0.1, code_grader({"chunk_records"}, CHUNK_TESTS, chunk_structure)),
    ]
    security_cases = [
        ("command_injection_vulnerable", "vulnerable", {"CWE-78", "CWE-078"}, "Python:\n```python\nimport subprocess\ndef ping(host):\n    return subprocess.check_output('ping -c 1 ' + host, shell=True, text=True)\n```"),
        ("command_injection_safe", "safe", set(), "Python:\n```python\nimport ipaddress, subprocess\ndef ping(host):\n    addr = str(ipaddress.ip_address(host))\n    return subprocess.check_output(['ping', '-c', '1', addr], text=True)\n```"),
        ("pickle_vulnerable", "vulnerable", {"CWE-502"}, "Python web handler:\n```python\ndef restore(request):\n    blob = base64.b64decode(request.form['snapshot'])\n    return pickle.loads(blob)\n```"),
        ("pickle_safe", "safe", set(), "Python web handler:\n```python\ndef restore(request):\n    obj = json.loads(request.form['snapshot'])\n    if not isinstance(obj, dict) or set(obj) - {'theme', 'page_size'}:\n        raise ValueError('invalid snapshot')\n    return {'theme': str(obj.get('theme', 'light')), 'page_size': min(100, max(1, int(obj.get('page_size', 20))))}\n```"),
        ("jwt_confusion_vulnerable", "vulnerable", {"CWE-347"}, "Python JWT verifier; PUBLIC_KEY is published:\n```python\ndef decode_token(token):\n    return jwt.decode(token, PUBLIC_KEY, algorithms=['RS256', 'HS256'], audience='payments')\n```"),
        ("jwt_confusion_safe", "safe", set(), "Python JWT verifier; PUBLIC_KEY is published:\n```python\ndef decode_token(token):\n    return jwt.decode(token, PUBLIC_KEY, algorithms=['RS256'], audience='payments', options={'require': ['exp', 'iat']})\n```"),
        ("ansible_toctou_vulnerable", "vulnerable", {"CWE-367", "CWE-732"}, "Ansible:\n```yaml\n- copy:\n    content: '{{ maintenance_script }}'\n    dest: /tmp/maint.sh\n    mode: '0666'\n- command: /tmp/maint.sh\n  become: true\n```"),
        ("ansible_toctou_safe", "safe", set(), "Ansible:\n```yaml\n- copy:\n    content: '{{ maintenance_script }}'\n    dest: /usr/local/libexec/maint.sh\n    owner: root\n    group: root\n    mode: '0700'\n  become: true\n- command: /usr/local/libexec/maint.sh\n  become: true\n```"),
    ]
    for name, verdict, cwes, sample in security_cases:
        tasks.append(Task("security", name, SECURITY_SYSTEM,
                          "Review this sample using the required JSON schema.\n\n" + sample,
                          cap(1250), 0.0, security_grader(verdict, cwes)))
    return tasks


def http_json(method: str, url: str, payload: dict[str, Any] | None = None,
              timeout: float = 30.0) -> tuple[dict[str, Any], dict[str, str]]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"refusing unsafe HTTP endpoint: {url!r}")
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        # The URL scheme and authority were validated above.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:4000]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def run_command(command: list[str], timeout: int = 60, check_result: bool = True,
                max_output_chars: int = 8000) -> dict[str, Any]:
    started = time.monotonic()
    # Every caller supplies argv from an internal fixed command table.
    run = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # nosec B603
                         timeout=timeout, check=False)
    result = {"command": command, "returncode": run.returncode,
              "output": run.stdout[-max_output_chars:], "elapsed_seconds": time.monotonic() - started}
    if check_result and run.returncode != 0:
        raise RuntimeError(f"command failed ({run.returncode}): {' '.join(command)}\n{run.stdout[-2000:]}")
    return result


def sudo(command: list[str], **kwargs: Any) -> dict[str, Any]:
    return run_command(["sudo", "-n", *command], **kwargs)


def parse_parameter_billions(text: str) -> float | None:
    compact = text.upper().replace(" ", "")
    values: list[float] = []
    for suffix, divisor in (("B", 1.0), ("M", 1000.0)):
        search_from = 0
        while (end := compact.find(suffix, search_from)) >= 0:
            start = end - 1
            while start >= 0 and (compact[start].isdigit() or compact[start] == "."):
                start -= 1
            number = compact[start + 1:end]
            with contextlib.suppress(ValueError):
                values.append(float(number) / divisor)
            search_from = end + 1
    return max(values) if values else None


def discover_models() -> dict[str, list[dict[str, Any]]]:
    models: dict[str, list[dict[str, Any]]] = {}
    for runtime, base in OPENAI_ENDPOINTS.items():
        response, _ = http_json("GET", base.rstrip("/") + "/v1/models", timeout=15)
        models[runtime] = list(response.get("data", []))
    response, _ = http_json("GET", OLLAMA_URL.rstrip("/") + OLLAMA_TAGS_PATH, timeout=15)
    models["ollama"] = list(response.get("models", []))
    return models


PREFERENCES = {
    "llamacpp": {
        "chat": ("Llama-3.3-70B-Instruct-Q4_K_M",),
        "story": ("Llama-3.3-70B-Instruct-Q4_K_M", "Command-R-35B"),
        "code_generation": ("Qwen3-Coder-30B-A3B-Instruct-Q4_K_M", "Qwen2.5-Coder-32B"),
        "code_refactoring": ("Qwen3-Coder-30B-A3B-Instruct-Q4_K_M", "Qwen2.5-Coder-32B"),
        "security": ("DeepSeek-R1-Distill-Qwen-32B-Q4_K_M", "Qwen3-Coder-30B"),
    },
    "lmstudio": {suite: ("qwen3-coder-30b-phase6", "qwen3-coder-30b-a3b-instruct") for suite in SUITES},
    "ollama": {
        "chat": ("llama3.3", "qwen3", "llama3.2"),
        "story": ("llama3.3", "qwen3", "llama3.2"),
        "code_generation": ("qwen3-coder", "qwen2.5-coder", "deepseek-coder"),
        "code_refactoring": ("qwen3-coder", "qwen2.5-coder", "deepseek-coder"),
        "security": ("deepseek-r1", "qwen3", "qwen2.5"),
    },
}


def model_id(model: dict[str, Any]) -> str:
    return str(model.get("id") or model.get("name") or model.get("model"))


def preferred_model(runtime: str, suite: str, available: list[dict[str, Any]]) -> dict[str, Any] | None:
    for fragment in PREFERENCES[runtime][suite]:
        match = next((item for item in available if fragment.lower() in model_id(item).lower()), None)
        if match:
            return match
    return None


def resolve_model_choice(runtime: str, suite: str, available: list[dict[str, Any]],
                         warnings: list[str]) -> dict[str, Any]:
    env_key = f"FRAMEWORK_BENCH_{runtime.upper()}_{suite.upper()}_MODEL"
    override = os.getenv(env_key)
    if override:
        chosen = next((item for item in available if model_id(item) == override), None)
        if chosen is None:
            raise RuntimeError(f"{env_key}={override!r} is not exposed by {runtime}")
        return chosen
    chosen = preferred_model(runtime, suite, available)
    if chosen:
        return chosen
    chosen = max(available, key=lambda item: parse_parameter_billions(
        str(item.get("details", {}).get("parameter_size", ""))) or 0.0)
    warnings.append(f"{runtime}/{suite}: no preferred model present; using {model_id(chosen)}")
    return chosen


def describe_selection(runtime: str, suite: str, chosen: dict[str, Any],
                       warnings: list[str]) -> dict[str, Any]:
    identifier = model_id(chosen)
    reported_size = str(chosen.get("details", {}).get("parameter_size", ""))
    billions = parse_parameter_billions(reported_size) or parse_parameter_billions(identifier)
    threshold = 7.0 if suite in ("chat", "story") else 14.0
    eligible = billions is None or billions >= threshold
    reason = ("meets model-size quality floor" if eligible
              else f"{billions:g}B is below {threshold:g}B quality floor")
    if not eligible:
        warnings.append(f"{runtime}/{suite}: {identifier} is smoke-only ({reason})")
    return {"id": identifier, "quality_eligible": eligible,
            "eligibility_reason": reason, "reported_parameter_billions": billions}


def choose_models(inventory: dict[str, list[dict[str, Any]]],
                  runtimes: tuple[str, ...] = ("llamacpp", "lmstudio", "ollama"),
                  suites: tuple[str, ...] = SUITES) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    warnings: list[str] = []
    for runtime in runtimes:
        available = inventory[runtime]
        if not available:
            raise RuntimeError(f"{runtime} exposes no models")
        for suite in suites:
            chosen = resolve_model_choice(runtime, suite, available, warnings)
            selected[(runtime, suite)] = describe_selection(runtime, suite, chosen, warnings)
    return selected, warnings


def read_integer(path: Path) -> int | None:
    with contextlib.suppress(OSError, ValueError):
        return int(path.read_text(encoding="utf-8").strip())
    return None


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    with Path("/proc/meminfo").open(encoding="utf-8") as source:
        for line in source:
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    return values


def read_cpu_ticks() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    ticks = [int(value) for value in fields]
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    return sum(ticks), idle


def read_gpu_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        device = card / "device"
        busy = read_integer(device / "gpu_busy_percent")
        if busy is None:
            continue
        metrics.update({"drm_card": card.name, "gpu_busy_percent": busy})
        gtt = read_integer(device / "mem_info_gtt_used")
        if gtt is not None:
            metrics["gtt_used_bytes"] = gtt
        break
    return metrics


def read_thermal_metrics() -> dict[str, Any]:
    temperatures: list[float] = []
    powers: list[float] = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon[0-9]*"):
        for item in hwmon.glob("temp*_input"):
            value = read_integer(item)
            if value is not None:
                temperatures.append(value / 1000)
        for item in hwmon.glob("power*_average"):
            value = read_integer(item)
            if value is not None:
                powers.append(value / 1_000_000)
    metrics: dict[str, Any] = {}
    if temperatures:
        metrics["temperature_max_c"] = max(temperatures)
    if powers:
        metrics["power_total_w"] = sum(powers)
    return metrics


def read_io_counters() -> dict[str, int]:
    network_rx = network_tx = 0
    for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]:
        name, raw = line.split(":", 1)
        if name.strip() == "lo":
            continue
        fields = raw.split()
        network_rx += int(fields[0])
        network_tx += int(fields[8])
    disk_read_sectors = disk_write_sectors = 0
    for line in Path("/proc/diskstats").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 10 and re.fullmatch(r"(?:nvme\d+n\d+|sd[a-z]+)", fields[2]):
            disk_read_sectors += int(fields[5])
            disk_write_sectors += int(fields[9])
    return {"network_rx_bytes": network_rx, "network_tx_bytes": network_tx,
            "disk_read_bytes": disk_read_sectors * 512,
            "disk_write_bytes": disk_write_sectors * 512}


def calculate_cpu_percent(previous: tuple[int, int] | None,
                          current: tuple[int, int]) -> float | None:
    if previous is None:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    return 100 * (total_delta - idle_delta) / total_delta if total_delta > 0 else None


def read_host_sample(previous_cpu: tuple[int, int] | None) -> tuple[dict[str, Any], tuple[int, int]]:
    current_cpu = read_cpu_ticks()
    memory = read_meminfo()
    sample: dict[str, Any] = {
        "recorded_at": utc_now(), "monotonic": time.monotonic(),
        "load_1m": os.getloadavg()[0],
        "memory_total_bytes": memory.get("MemTotal"),
        "memory_available_bytes": memory.get("MemAvailable"),
        "memory_used_bytes": memory.get("MemTotal", 0) - memory.get("MemAvailable", 0),
        "swap_used_bytes": memory.get("SwapTotal", 0) - memory.get("SwapFree", 0),
        "cpu_busy_percent": calculate_cpu_percent(previous_cpu, current_cpu),
    }
    sample.update(read_gpu_metrics())
    sample.update(read_thermal_metrics())
    sample.update(read_io_counters())
    return sample, current_cpu


SUMMARY_METRICS = ("cpu_busy_percent", "load_1m", "memory_used_bytes", "memory_available_bytes",
                   "swap_used_bytes", "gpu_busy_percent", "gtt_used_bytes",
                   "temperature_max_c", "power_total_w")
COUNTER_METRICS = ("network_rx_bytes", "network_tx_bytes", "disk_read_bytes", "disk_write_bytes")


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"sample_count": len(samples)}
    for metric in SUMMARY_METRICS:
        values = [item[metric] for item in samples if isinstance(item.get(metric), (int, float))]
        if values:
            summary[metric] = {"start": values[0], "end": values[-1],
                               "min": min(values), "max": max(values),
                               "mean": statistics.fmean(values)}
    for metric in COUNTER_METRICS:
        values = [item[metric] for item in samples if isinstance(item.get(metric), int)]
        if values:
            summary[metric] = {"start": values[0], "end": values[-1],
                               "delta": max(0, values[-1] - values[0])}
    return summary


def read_runtime_states() -> dict[str, Any]:
    systemd = run_command(["sudo", "-n", "systemctl", "is-active",
                           LMSTUDIO_SERVICE, LMSTUDIO_TIMER], check_result=False)
    containers = run_command(["sudo", "-n", "docker", "inspect", "-f",
                              "{{.Name}}={{.State.Status}}", LLAMACPP_CONTAINER,
                              OLLAMA_CONTAINER], check_result=False)
    return {"systemd": systemd["output"].splitlines(),
            "containers": containers["output"].splitlines()}


class HostMonitor:
    def __init__(self, output_path: Path, interval: float = 1.0) -> None:
        self.output_path = output_path
        self.interval = interval
        self.stop_event = threading.Event()
        self.samples: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._sample_loop, name="host-monitor", daemon=True)
        self.thread.start()

    def _sample_loop(self) -> None:
        previous_cpu = None
        sample_number = 0
        with self.output_path.open("a", encoding="utf-8", buffering=1) as output:
            while not self.stop_event.is_set():
                try:
                    sample, previous_cpu = read_host_sample(previous_cpu)
                    if sample_number % 10 == 0:
                        sample["runtime_states"] = read_runtime_states()
                except Exception as exc:
                    sample = {"recorded_at": utc_now(), "monotonic": time.monotonic(),
                              "sample_error": f"{type(exc).__name__}: {exc}"}
                with self.lock:
                    self.samples.append(sample)
                output.write(json.dumps(sample, sort_keys=True) + "\n")
                sample_number += 1
                self.stop_event.wait(self.interval)

    def mark(self) -> int:
        with self.lock:
            return len(self.samples)

    def summary_since(self, marker: int) -> dict[str, Any]:
        with self.lock:
            interval = list(self.samples[marker:])
        return summarize_samples(interval)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=max(2.0, self.interval * 2))


class RuntimeCoordinator:
    def __init__(self, enabled: bool, log: Callable[[str], None]) -> None:
        self.enabled = enabled
        self.log = log
        self.initial: dict[str, bool] = {}
        self.current: str | None = None

    @staticmethod
    def service_active(unit: str) -> bool:
        result = sudo(["systemctl", "is-active", "--quiet", unit], check_result=False)
        return result["returncode"] == 0

    @staticmethod
    def container_active(container: str) -> bool:
        result = sudo(["docker", "inspect", "-f", "{{.State.Running}}", container],
                      check_result=False)
        return result["returncode"] == 0 and result["output"].strip() == "true"

    def capture(self) -> None:
        if not self.enabled:
            return
        sudo(["true"])
        self.initial = {
            LMSTUDIO_SERVICE: self.service_active(LMSTUDIO_SERVICE),
            LMSTUDIO_TIMER: self.service_active(LMSTUDIO_TIMER),
            LLAMACPP_CONTAINER: self.container_active(LLAMACPP_CONTAINER),
            OLLAMA_CONTAINER: self.container_active(OLLAMA_CONTAINER),
        }
        self.log(f"Captured service state: {self.initial}")

    def _stop_lmstudio(self) -> None:
        sudo(["systemctl", "stop", LMSTUDIO_TIMER], check_result=False)
        sudo(["systemctl", "stop", LMSTUDIO_SERVICE], check_result=False)

    def _unload_ollama(self) -> None:
        with contextlib.suppress(Exception):
            response, _ = http_json("GET", OLLAMA_URL.rstrip("/") + OLLAMA_TAGS_PATH, timeout=10)
            for model in response.get("models", []):
                http_json("POST", OLLAMA_URL.rstrip("/") + "/api/generate",
                          {"model": model_id(model), "keep_alive": 0}, timeout=30)

    def prepare(self, runtime: str) -> None:
        if not self.enabled or runtime == self.current:
            return
        self.log(f"Preparing isolated runtime: {runtime}")
        with contextlib.suppress(Exception):
            http_json("POST", "http://127.0.0.1:8188/free",
                      {"unload_models": True, "free_memory": True}, timeout=15)
        if runtime == "llamacpp":
            self._stop_lmstudio()
            self._unload_ollama()
            sudo(["docker", "start", LLAMACPP_CONTAINER], check_result=False)
        elif runtime == "lmstudio":
            sudo(["docker", "restart", LLAMACPP_CONTAINER], timeout=90, check_result=False)
            self._unload_ollama()
            sudo(["systemctl", "start", LMSTUDIO_SERVICE], timeout=180)
        elif runtime == "ollama":
            self._stop_lmstudio()
            sudo(["docker", "restart", LLAMACPP_CONTAINER], timeout=90, check_result=False)
            sudo(["docker", "start", OLLAMA_CONTAINER], check_result=False)
        self.current = runtime
        time.sleep(3)

    def restore(self) -> None:
        if not self.enabled or not self.initial:
            return
        self.log("Restoring initial service states")
        try:
            self._unload_ollama()
            sudo(["docker", "restart", LLAMACPP_CONTAINER], timeout=90, check_result=False)
            for container in (LLAMACPP_CONTAINER, OLLAMA_CONTAINER):
                action = "start" if self.initial[container] else "stop"
                sudo(["docker", action, container], timeout=90, check_result=False)
            self._stop_lmstudio()
            if self.initial[LMSTUDIO_SERVICE]:
                sudo(["systemctl", "start", LMSTUDIO_SERVICE], timeout=180, check_result=False)
            if self.initial[LMSTUDIO_TIMER]:
                sudo(["systemctl", "start", LMSTUDIO_TIMER], check_result=False)
        except Exception as exc:
            self.log(f"WARNING: service-state restoration failed: {exc}")


ANOMALY_RE = re.compile(
    r"out of memory|oom-kill|killed process|segfault|general protection fault|"
    r"amdgpu.*(?:reset|timeout|ring|fault)|device lost|hip error|rocm.*error|"
    r"kernel panic|watchdog|fatal error|core dumped|container.*(?:die|killed)",
    re.IGNORECASE,
)


def command_evidence(command: list[str], timeout: int = 30,
                     max_output_chars: int = 100_000) -> dict[str, Any]:
    try:
        return run_command(command, timeout=timeout, check_result=False,
                           max_output_chars=max_output_chars)
    except Exception as exc:
        return {"command": command, "returncode": None,
                "output": "", "error": f"{type(exc).__name__}: {exc}"}


def runtime_logs(runtime: str, since_epoch: float) -> dict[str, Any]:
    since = str(int(since_epoch))
    if runtime == "llamacpp":
        command = ["sudo", "-n", "docker", "logs", "--since", since, LLAMACPP_CONTAINER]
    elif runtime == "ollama":
        command = ["sudo", "-n", "docker", "logs", "--since", since, OLLAMA_CONTAINER]
    else:
        command = ["sudo", "-n", "journalctl", "--since", f"@{since}", "--no-pager",
                   "-o", "short-iso", "-u", LMSTUDIO_SERVICE, "-u", LMSTUDIO_TIMER]
    return command_evidence(command)


def kernel_logs(since_epoch: float) -> dict[str, Any]:
    return command_evidence(["sudo", "-n", "journalctl", "-k", "--since",
                             f"@{int(since_epoch)}", "--no-pager", "-o", "short-iso"])


def api_health() -> dict[str, Any]:
    health: dict[str, Any] = {}
    endpoints = {**{name: base.rstrip("/") + "/v1/models"
                    for name, base in OPENAI_ENDPOINTS.items()},
                 "ollama": OLLAMA_URL.rstrip("/") + OLLAMA_TAGS_PATH}
    for name, url in endpoints.items():
        started = time.monotonic()
        try:
            response, _ = http_json("GET", url, timeout=10)
            health[name] = {"ok": True, "elapsed_seconds": time.monotonic() - started,
                            "model_count": len(response.get("data", response.get("models", [])))}
        except Exception as exc:
            health[name] = {"ok": False, "elapsed_seconds": time.monotonic() - started,
                            "error": f"{type(exc).__name__}: {exc}"}
    return health


def system_snapshot() -> dict[str, Any]:
    commands = {
        "uname": ["uname", "-a"],
        "uptime": ["uptime"],
        "memory": ["free", "-b"],
        "processes": ["ps", "-eo", "pid,ppid,user,stat,%cpu,%mem,rss,etimes,comm,args", "--sort=-rss"],
        "systemd": ["sudo", "-n", "systemctl", "status", "--no-pager",
                    LMSTUDIO_SERVICE, LMSTUDIO_TIMER],
        "containers": ["sudo", "-n", "docker", "inspect", LLAMACPP_CONTAINER, OLLAMA_CONTAINER],
        "container_stats": ["sudo", "-n", "docker", "stats", "--no-stream", "--no-trunc",
                            LLAMACPP_CONTAINER, OLLAMA_CONTAINER],
        "rocm": ["rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--showpower", "--json"],
    }
    evidence = {name: command_evidence(command, max_output_chars=50_000)
                for name, command in commands.items()}
    sample, _ = read_host_sample(None)
    return {"recorded_at": utc_now(), "host_sample": sample,
            "api_health": api_health(), "commands": evidence}


def find_anomalies(*logs: dict[str, Any]) -> list[str]:
    matches: list[str] = []
    for log in logs:
        for line in str(log.get("output", "")).splitlines():
            if ANOMALY_RE.search(line):
                matches.append(line[-2000:])
    return matches[-100:]


class IncidentCollector:
    def __init__(self, run_dir: Path, run_started_epoch: float) -> None:
        self.run_dir = run_dir
        self.run_started_epoch = run_started_epoch
        self.incident_dir = run_dir / "incidents"
        self.system_log_dir = run_dir / "system-logs"
        self.incident_dir.mkdir(mode=0o750, exist_ok=True)
        self.system_log_dir.mkdir(mode=0o750, exist_ok=True)

    def inspect_request(self, record: dict[str, Any], since_epoch: float) -> list[str]:
        kernel = kernel_logs(since_epoch)
        service = runtime_logs(record["runtime"], since_epoch)
        anomalies = find_anomalies(kernel, service)
        if not record.get("request_ok") or anomalies:
            self.write_incident(record, since_epoch, kernel, service, anomalies)
        return anomalies

    def write_incident(self, record: dict[str, Any], since_epoch: float,
                       kernel: dict[str, Any], service: dict[str, Any],
                       anomalies: list[str]) -> None:
        identifier = "-".join((record["runtime"], record["suite"], record["task"],
                               f"rep{record['repetition']}"))
        safe_identifier = re.sub(r"[^a-zA-Z0-9_.-]", "_", identifier)
        payload = {"schema_version": 1, "captured_at": utc_now(),
                   "request_started_epoch": since_epoch,
                   "request_identity": {key: record.get(key) for key in
                                        ("runtime", "model", "suite", "task", "repetition")},
                   "request_error": record.get("error"), "anomalies": anomalies,
                   "kernel_logs": kernel, "runtime_logs": service,
                   "system_snapshot": system_snapshot()}
        write_json(self.incident_dir / f"{safe_identifier}.json", payload)

    def capture_run_evidence(self, label: str) -> None:
        write_json(self.run_dir / f"system-snapshot-{label}.json", system_snapshot())
        kernel = kernel_logs(self.run_started_epoch)
        (self.system_log_dir / f"kernel-{label}.log").write_text(
            str(kernel.get("output", "")), encoding="utf-8")
        for runtime in ("llamacpp", "lmstudio", "ollama"):
            logs = runtime_logs(runtime, self.run_started_epoch)
            (self.system_log_dir / f"{runtime}-{label}.log").write_text(
                str(logs.get("output", "")), encoding="utf-8")


def request_completion(runtime: str, model: str, task: Task, seed: int,
                       timeout: float) -> dict[str, Any]:
    if runtime in OPENAI_ENDPOINTS:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": task.system},
                         {"role": "user", "content": task.prompt}],
            "temperature": task.temperature,
            "max_tokens": task.max_tokens,
            "seed": seed,
            "stream": False,
        }
        response, headers = http_json("POST", OPENAI_ENDPOINTS[runtime].rstrip("/") + "/v1/chat/completions",
                                      payload, timeout=timeout)
        message = response.get("choices", [{}])[0].get("message", {})
        content = message.get("content") or ""
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]
        usage = response.get("usage", {})
        return {"content": str(content), "response": response, "headers": headers,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens")}
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": task.system},
                     {"role": "user", "content": task.prompt}],
        "stream": False,
        "keep_alive": 0,
        "options": {"temperature": task.temperature, "seed": seed, "num_predict": task.max_tokens},
    }
    response, headers = http_json("POST", OLLAMA_URL.rstrip("/") + "/api/chat", payload, timeout=timeout)
    return {"content": str(response.get("message", {}).get("content", "")),
            "response": response, "headers": headers,
            "prompt_tokens": response.get("prompt_eval_count"),
            "completion_tokens": response.get("eval_count"),
            "server_prompt_seconds": (response.get("prompt_eval_duration") or 0) / 1_000_000_000,
            "server_eval_seconds": (response.get("eval_duration") or 0) / 1_000_000_000,
            "server_load_seconds": (response.get("load_duration") or 0) / 1_000_000_000,
            "server_total_seconds": (response.get("total_duration") or 0) / 1_000_000_000}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def permitted_results_roots() -> tuple[Path, ...]:
    return (DEFAULT_RESULTS_ROOT.resolve(),
            (Path.home() / "framework-ai-benchmark-results").resolve())


def validate_results_root(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser().resolve(strict=False)
    if not any(candidate == base or candidate.is_relative_to(base)
               for base in permitted_results_roots()):
        allowed = ", ".join(str(path) for path in permitted_results_roots())
        raise ValueError(f"results path must be within one of: {allowed}")
    return candidate


def resolve_run_directory(args: argparse.Namespace) -> Path:
    results_root = validate_results_root(args.results_root)
    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve(strict=False)
        if not run_dir.is_relative_to(results_root) or not RUN_NAME_RE.fullmatch(run_dir.name):
            raise ValueError("--run-dir must be a timestamped direct child of --results-root")
    else:
        run_dir = results_root / dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)  # Path is confined to an allowlisted operator-owned root.
    if run_dir.is_symlink() or run_dir.resolve() != run_dir:
        raise ValueError(f"run directory must not be a symlink: {run_dir}")
    return run_dir


def acquire_run_lock() -> Any:
    runtime_dir = Path("/run/user") / str(os.getuid())
    stat = runtime_dir.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o022:
        raise PermissionError(f"unsafe user runtime directory permissions: {runtime_dir}")
    lock_path = runtime_dir / "framework-ai-benchmark.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    lock_file = os.fdopen(descriptor, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise
    return lock_file


class RunLogger:
    def __init__(self, path: Path) -> None:
        self.file = path.open("a", encoding="utf-8", buffering=1)

    def __call__(self, message: str) -> None:
        line = f"{utc_now()} {message}"
        print(line, flush=True)
        self.file.write(line + "\n")

    def close(self) -> None:
        self.file.close()


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def aggregate_row(key: tuple[str, str, str, bool],
                  items: list[dict[str, Any]]) -> dict[str, Any]:
    runtime, suite, model, eligible = key
    successful = [item for item in items if item.get("request_ok")]
    graded = [item for item in successful if "grade" in item]
    elapsed = [item["elapsed_seconds"] for item in successful]
    rates = [item["tokens_per_second"] for item in successful
             if item.get("tokens_per_second") is not None]
    return {
        "runtime": runtime, "suite": suite, "model": model,
        "quality_eligible": eligible, "requests": len(items),
        "request_success_rate": len(successful) / len(items),
        "mean_score": statistics.fmean(item["grade"]["score"] for item in graded) if graded else None,
        "strict_pass_rate": statistics.fmean(int(item["grade"]["passed"]) for item in graded) if graded else None,
        "mean_elapsed_seconds": statistics.fmean(elapsed) if elapsed else None,
        "mean_tokens_per_second": statistics.fmean(rates) if rates else None,
    }


def summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        key = (item["runtime"], item["suite"], item["model"], item["quality_eligible"])
        groups[key].append(item)
    return [aggregate_row(key, items) for key, items in sorted(groups.items())]


def format_metric(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def markdown_row(row: dict[str, Any]) -> str:
    return (f"| {row['runtime']} | {row['suite']} | `{row['model']}` | "
            f"{'yes' if row['quality_eligible'] else 'no'} | {row['requests']} | "
            f"{row['request_success_rate']:.0%} | {format_metric(row['mean_score'])} | "
            f"{format_metric(row['strict_pass_rate'])} | {format_metric(row['mean_elapsed_seconds'])} | "
            f"{format_metric(row['mean_tokens_per_second'])} |")


def make_summary(results: list[dict[str, Any]], manifest: dict[str, Any], run_dir: Path,
                 completed: bool) -> None:
    rows = summary_rows(results)
    summary = {"completed": completed, "generated_at": utc_now(), "rows": rows,
               "total_results": len(results), "warnings": manifest.get("warnings", [])}
    write_json(run_dir / "summary.json", summary)
    lines = ["# Framework AI benchmark summary", "", f"Status: **{'complete' if completed else 'partial'}**",
             "", f"Started: `{manifest['started_at']}`", f"Updated: `{summary['generated_at']}`", "",
             "| Runtime | Suite | Model | Eligible | N | Request success | Mean score | Strict pass | Mean seconds | Mean tok/s |",
             "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    lines.extend(markdown_row(row) for row in rows)
    if manifest.get("warnings"):
        lines.extend(["", "## Warnings", ""] + [f"- {warning}" for warning in manifest["warnings"]])
    lines.extend(["", "Raw request/response records and grader details are in `results.jsonl`.",
                  "Creative-writing scores measure constraints and lexical variety, not subjective literary merit.",
                  "Ineligible smoke-only models are excluded from any quality conclusion.", ""])
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def performance_metrics(completion: dict[str, Any], elapsed: float) -> dict[str, Any]:
    response = completion.get("response", {})
    timings = response.get("timings", {}) if isinstance(response, dict) else {}
    prompt_tokens = completion.get("prompt_tokens") or timings.get("prompt_n")
    completion_tokens = completion.get("completion_tokens") or timings.get("predicted_n")
    prompt_seconds = completion.get("server_prompt_seconds")
    generation_seconds = completion.get("server_eval_seconds")
    if prompt_seconds is None and timings.get("prompt_ms") is not None:
        prompt_seconds = timings["prompt_ms"] / 1000
    if generation_seconds is None and timings.get("predicted_ms") is not None:
        generation_seconds = timings["predicted_ms"] / 1000
    generation_rate = timings.get("predicted_per_second")
    if completion_tokens and generation_seconds:
        generation_rate = completion_tokens / generation_seconds
    elif completion_tokens:
        generation_rate = completion_tokens / elapsed
    return {
        "wall_seconds": elapsed,
        "first_output_latency_seconds": None,
        "first_output_latency_note": "not available from non-streaming compatibility request",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_eval_seconds": prompt_seconds,
        "generation_seconds": generation_seconds,
        "prompt_tokens_per_second": (prompt_tokens / prompt_seconds
                                     if prompt_tokens and prompt_seconds else timings.get("prompt_per_second")),
        "generation_tokens_per_second": generation_rate,
        "server_load_seconds": completion.get("server_load_seconds"),
        "server_total_seconds": completion.get("server_total_seconds"),
    }


def evaluation_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": record["runtime"], "model": record["model"],
        "quality_eligible": record["quality_eligible"], "suite": record["suite"],
        "task": record["task"], "repetition": record["repetition"], "seed": record["seed"],
        "input": record["request"], "output": record.get("response_text"),
        "request_ok": record.get("request_ok"), "request_error": record.get("error"),
        "deterministic_grade": record.get("grade"), "performance": record.get("performance"),
    }


def write_evaluation_guide(run_dir: Path) -> None:
    content = """# Cloud LLM evaluation guide

Evaluate each line of `evaluation-corpus.jsonl` independently. Judge the
`output` against the supplied system prompt, user prompt, and task suite.
Return JSONL with: runtime, model, suite, task, repetition, correctness_0_to_5,
usefulness_0_to_5, instruction_following_0_to_5, concise_rationale, and any
critical_error. Do not change a score because one runtime/model is familiar or
larger. Treat `quality_eligible: false` as metadata, not a scoring instruction.

For code and security tasks, use the deterministic grade as evidence but still
inspect the output for flaws the bounded grader may miss. For story tasks,
prioritize coherence, prose quality, originality, and satisfying resolution;
the deterministic grade covers only literal constraints. Do not include
operational files from `system-logs/` or `incidents/` in the cloud evaluation.
"""
    (run_dir / "cloud-evaluation-guide.md").write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", default="/storage/artifacts/framework-ai-benchmarks")
    parser.add_argument("--run-dir", help="resume/use an explicit run directory")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900.0, help="per-request seconds")
    parser.add_argument("--runtimes", nargs="+", choices=("llamacpp", "lmstudio", "ollama"),
                        default=["llamacpp", "lmstudio", "ollama"])
    parser.add_argument("--suites", nargs="+", choices=SUITES, default=list(SUITES))
    parser.add_argument("--smoke", action="store_true", help="shorter response caps; use with one repetition")
    parser.add_argument("--no-manage-runtime-memory", action="store_true",
                        help="do not stop/unload runtimes; unsafe for the default large-model matrix")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    return args


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", buffering=1) as output:
        output.write(json.dumps(value, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())


class BenchmarkRun:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_started_epoch = time.time()
        self.run_dir = resolve_run_directory(args)
        self.logger = RunLogger(self.run_dir / "run.log")
        self.coordinator = RuntimeCoordinator(not args.no_manage_runtime_memory, self.logger)
        self.monitor = HostMonitor(self.run_dir / "telemetry.jsonl")
        self.incidents = IncidentCollector(self.run_dir, self.run_started_epoch)
        self.results_path = self.run_dir / "results.jsonl"
        self.evaluation_path = self.run_dir / "evaluation-corpus.jsonl"
        self.manifest_path = self.run_dir / "manifest.json"
        self.existing, self.completed_keys = self.load_existing()
        self.all_results = list(self.existing)
        self.manifest: dict[str, Any] = {}
        self.selection: dict[tuple[str, str], dict[str, Any]] = {}

    def handle_signal(self, signum: int, _frame: Any) -> None:
        self.logger(f"Received signal {signum}; stopping after current operation")
        raise KeyboardInterrupt

    def load_existing(self) -> tuple[list[dict[str, Any]], set[tuple[str, str, str, int]]]:
        existing: list[dict[str, Any]] = []
        completed: set[tuple[str, str, str, int]] = set()
        if not self.results_path.exists():
            return existing, completed
        for line in self.results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                existing.append(item)
                completed.add((item["runtime"], item["suite"], item["task"], item["repetition"]))
        return existing, completed

    def prepare_manifest(self) -> list[str]:
        inventory = discover_models()
        self.selection, warnings = choose_models(inventory, tuple(self.args.runtimes), tuple(self.args.suites))
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self.manifest["resumed_at"] = utc_now()
        else:
            self.manifest = {
                "started_at": utc_now(), "hostname": socket.gethostname(),
                "platform": platform.platform(), "python": sys.version,
                "arguments": vars(self.args), "inventory": inventory,
                "selection": {f"{runtime}/{suite}": value
                              for (runtime, suite), value in self.selection.items()},
                "warnings": warnings,
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }
        write_json(self.manifest_path, self.manifest)
        return warnings

    def pending_work(self) -> list[tuple[str, Task, int]]:
        tasks = [task for task in build_tasks(self.args.smoke) if task.suite in self.args.suites]
        work = [(runtime, task, repetition)
                for runtime in self.args.runtimes
                for task in tasks
                for repetition in range(1, self.args.repetitions + 1)
                if (runtime, task.suite, task.name, repetition) not in self.completed_keys]
        work.sort(key=lambda item: (self.args.runtimes.index(item[0]),
                                    self.selection[(item[0], item[1].suite)]["id"],
                                    SUITES.index(item[1].suite), item[1].name, item[2]))
        return work

    def create_record(self, runtime: str, task: Task, repetition: int) -> dict[str, Any]:
        chosen = self.selection[(runtime, task.suite)]
        return {
            "recorded_at": utc_now(), "runtime": runtime, "model": chosen["id"],
            "quality_eligible": chosen["quality_eligible"],
            "eligibility_reason": chosen["eligibility_reason"], "suite": task.suite,
            "task": task.name, "repetition": repetition, "seed": 1000 + repetition,
            "request": {"system": task.system, "prompt": task.prompt,
                        "temperature": task.temperature, "max_tokens": task.max_tokens},
        }

    def call_model(self, record: dict[str, Any], task: Task) -> None:
        started = time.monotonic()
        try:
            completion = request_completion(record["runtime"], record["model"], task,
                                            record["seed"], self.args.timeout)
            elapsed = time.monotonic() - started
            content = completion.pop("content")
            performance = performance_metrics(completion, elapsed)
            record.update({"request_ok": True, "elapsed_seconds": elapsed,
                           "tokens_per_second": performance["generation_tokens_per_second"],
                           "performance": performance, "response_text": content,
                           "completion": completion, "grade": task.grader(content)})
            self.logger(f"score={record['grade']['score']:.2f} "
                        f"strict_pass={record['grade']['passed']} elapsed={elapsed:.1f}s")
        except Exception as exc:
            elapsed = time.monotonic() - started
            record.update({"request_ok": False, "elapsed_seconds": elapsed,
                           "performance": {"wall_seconds": elapsed},
                           "error": f"{type(exc).__name__}: {exc}",
                           "traceback": traceback.format_exc(limit=8)})
            self.logger(f"ERROR: {record['error']}")

    def collect_request_evidence(self, record: dict[str, Any], request_started: float,
                                 telemetry_marker: int) -> None:
        record["resource_usage"] = self.monitor.summary_since(telemetry_marker)
        try:
            anomalies = self.incidents.inspect_request(record, request_started)
            record["log_anomalies"] = anomalies
            if anomalies:
                self.logger(f"WARNING: captured {len(anomalies)} crash/error log signatures")
        except Exception as exc:
            record["evidence_collection_error"] = f"{type(exc).__name__}: {exc}"
            self.logger(f"WARNING: request evidence collection failed: {exc}")

    def checkpoint(self, record: dict[str, Any], index: int, total: int) -> None:
        append_jsonl(self.results_path, record)
        append_jsonl(self.evaluation_path, evaluation_record(record))
        self.all_results.append(record)
        write_json(self.run_dir / "progress.json", {
            "updated_at": utc_now(), "completed_this_invocation": index,
            "pending_this_invocation": total - index, "total_records": len(self.all_results),
            "last": {key: record.get(key) for key in
                     ("runtime", "model", "suite", "task", "repetition", "request_ok")},
        })
        make_summary(self.all_results, self.manifest, self.run_dir, completed=False)

    def execute_request(self, item: tuple[str, Task, int], index: int, total: int) -> None:
        runtime, task, repetition = item
        self.coordinator.prepare(runtime)
        record = self.create_record(runtime, task, repetition)
        self.logger(f"[{index}/{total}] {runtime}/{record['model']}/{task.suite}/{task.name}/rep{repetition}")
        request_started = time.time()
        telemetry_marker = self.monitor.mark()
        self.call_model(record, task)
        self.collect_request_evidence(record, request_started, telemetry_marker)
        self.checkpoint(record, index, total)
        if self.args.fail_fast and not record["request_ok"]:
            raise RuntimeError(record["error"])

    def rebuild_evaluation_corpus(self) -> None:
        self.evaluation_path.write_text("", encoding="utf-8")
        for record in self.existing:
            append_jsonl(self.evaluation_path, evaluation_record(record))

    def run_matrix(self) -> int:
        warnings = self.prepare_manifest()
        for warning in warnings:
            self.logger(f"WARNING: {warning}")
        work = self.pending_work()
        self.rebuild_evaluation_corpus()
        write_evaluation_guide(self.run_dir)
        self.coordinator.capture()
        self.monitor.start()
        self.incidents.capture_run_evidence("initial")
        self.logger(f"Run directory: {self.run_dir}")
        self.logger(f"Pending requests: {len(work)}; already complete: {len(self.existing)}")
        for index, item in enumerate(work, 1):
            self.execute_request(item, index, len(work))
        make_summary(self.all_results, self.manifest, self.run_dir, completed=True)
        write_json(self.run_dir / "progress.json", {"updated_at": utc_now(), "complete": True,
                                                     "total_records": len(self.all_results)})
        self.logger(f"Benchmark complete: {self.run_dir / 'summary.md'}")
        return 0

    def execute(self) -> int:
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
        try:
            return self.run_matrix()
        except KeyboardInterrupt:
            self.logger("Benchmark interrupted; checkpoint is resumable with --run-dir")
            return 130
        except Exception as exc:
            self.logger(f"FATAL: {type(exc).__name__}: {exc}")
            self.logger(traceback.format_exc(limit=12))
            with contextlib.suppress(Exception):
                self.incidents.capture_run_evidence("fatal")
            return 1
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.coordinator.restore()
        with contextlib.suppress(Exception):
            self.incidents.capture_run_evidence("final")
        self.monitor.stop()
        self.logger.close()


def main() -> int:
    args = parse_args()
    try:
        lock_file = acquire_run_lock()
    except BlockingIOError:
        print("Another framework benchmark is already running.", file=sys.stderr)
        return 2
    try:
        return BenchmarkRun(args).execute()
    except Exception as exc:
        print(f"Benchmark initialization failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        lock_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
