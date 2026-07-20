#!/usr/bin/env python3
"""Autonomous ComfyUI smoke and image-generation benchmark for Framework.

The harness deliberately uses only Python's standard library. It submits
known-good Z-Image Turbo API workflows, retains every generated image and
workflow, samples host/GPU/container resources, and captures diagnostic state
when ComfyUI or the kernel reports an error.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import statistics
import struct
import subprocess  # nosec B404 -- fixed local administrative commands only
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable


COMFY_URL = os.getenv("FRAMEWORK_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
DEFAULT_RESULTS_ROOT = Path("/storage/artifacts/framework-ai-benchmarks/comfyui")
COMFY_CONTAINER = "comfyui"
LLAMACPP_CONTAINER = "llamacpp-router"
OLLAMA_CONTAINER = "ollama"
LMSTUDIO_SERVICE = "lmstudio.service"
LMSTUDIO_TIMER = "lmstudio-healthcheck.timer"
MODEL = "z_image_turbo_bf16.safetensors"
TEXT_ENCODER = "qwen_3_4b.safetensors"
VAE = "ae.safetensors"

ANOMALY_RE = re.compile(
    r"out of memory|oom-kill|killed process|segfault|general protection fault|"
    r"amdgpu.*(?:reset|timeout|ring|fault)|device lost|hip error|rocm.*error|"
    r"kernel panic|watchdog|fatal error|core dumped|container.*(?:die|killed)",
    re.IGNORECASE,
)


@dataclasses.dataclass(frozen=True)
class ImageTask:
    name: str
    category: str
    prompt: str
    negative: str
    width: int
    height: int
    steps: int
    seed: int
    purpose: str


BASELINE_PROMPT = (
    "A polished red ceramic teapot centered on a pale oak table, a folded "
    "indigo linen napkin to its left and exactly three yellow lemons to its "
    "right, soft morning window light, realistic product photography, crisp "
    "materials, uncluttered neutral background"
)
BASELINE_NEGATIVE = "blurry, low quality, duplicate objects"


def smoke_tasks() -> list[ImageTask]:
    return [ImageTask(
        "functional_512", "smoke", BASELINE_PROMPT, BASELINE_NEGATIVE,
        512, 512, 4, 26072101,
        "Fast end-to-end API, model-load, sampler, VAE, PNG, and GPU check.",
    )]


def benchmark_tasks() -> list[ImageTask]:
    return [
        ImageTask(
            "baseline_unloaded_512", "cold-vs-warm", BASELINE_PROMPT,
            BASELINE_NEGATIVE, 512, 512, 9, 26072111,
            "First request after /free; includes model and text-encoder load cost.",
        ),
        ImageTask(
            "baseline_warm_512", "cold-vs-warm", BASELINE_PROMPT,
            BASELINE_NEGATIVE, 512, 512, 9, 26072112,
            "Warm repeat with a different seed so ComfyUI cannot cache the sampler output.",
        ),
        ImageTask(
            "baseline_768", "resolution-scaling", BASELINE_PROMPT,
            BASELINE_NEGATIVE, 768, 768, 9, 26072112,
            "Resolution-scaling point using the same prompt and seed as the warm 512 baseline.",
        ),
        ImageTask(
            "baseline_1024", "resolution-scaling", BASELINE_PROMPT,
            BASELINE_NEGATIVE, 1024, 1024, 9, 26072112,
            "Resolution-scaling point at the model's documented example size.",
        ),
        ImageTask(
            "photoreal_portrait", "photorealism",
            "Editorial environmental portrait of an elderly Maori woman who repairs watches, "
            "seated at a crowded workbench, silver hair, warm brown skin with natural texture, "
            "tiny brass gears and magnifying loupe, late-afternoon side light, 50mm documentary "
            "photography, honest expression, shallow depth of field",
            "plastic skin, extra fingers, deformed hands, glamour retouching, text, watermark",
            1024, 1024, 9, 26072121,
            "Tests faces, hands, materials, lighting, and photorealistic coherence.",
        ),
        ImageTask(
            "typography_poster", "typography",
            "A clean Swiss modernist event poster pinned flat to a white wall. The poster has "
            "only these words, all perfectly legible: FRAMEWORK AI on the first line, WINTER LAB "
            "on the second line, 21 JULY on the third line. Bold black sans-serif type, one red "
            "circle, strict grid layout, no other letters or numbers, straight-on photograph",
            "misspelled text, extra text, warped letters, illegible letters, watermark, tilted poster",
            1024, 1024, 9, 26072131,
            "Tests exact in-image text, counting, layout, and negative constraints.",
        ),
        ImageTask(
            "spatial_instructions", "prompt-adherence",
            "A square children's-book illustration: a small blue robot stands beneath a green "
            "umbrella in the exact center; two orange cats sit on the robot's left; one purple "
            "suitcase is on its right; a crescent moon is in the upper-left corner; a red paper "
            "airplane is in the upper-right corner. Flat cream background, bold ink outlines",
            "photorealistic, extra cats, extra robots, extra suitcases, text, watermark",
            1024, 1024, 9, 26072141,
            "Tests object counts, colors, left/right placement, and global composition.",
        ),
        ImageTask(
            "creative_surreal", "creativity",
            "An original surreal scene called The Cartographer of Forgotten Weather: a solitary "
            "figure maps a thunderstorm folded into translucent origami, while tiny migrating "
            "houses cross a salt desert and cast shadows shaped like forests, dreamlike but "
            "internally coherent, intricate mixed-media illustration, unusual color harmony, "
            "poetic visual storytelling, no familiar franchise imagery",
            "generic fantasy castle, stock photo, text, logo, watermark, incoherent clutter",
            1024, 1024, 9, 26072151,
            "Tests novelty, visual storytelling, composition, and coherent surrealism.",
        ),
    ]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_command(command: list[str], timeout: float = 60, check: bool = True,
                max_chars: int = 100_000) -> dict[str, Any]:
    completed = subprocess.run(  # nosec B603 -- argv is never interpreted by a shell
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=timeout, check=False,
    )
    output = completed.stdout[-max_chars:]
    if check and completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{output}")
    return {"command": command, "returncode": completed.returncode, "output": output}


def evidence(command: list[str], timeout: float = 60) -> dict[str, Any]:
    try:
        return run_command(command, timeout=timeout, check=False)
    except Exception as exc:
        return {"command": command, "returncode": None, "output": "",
                "error": f"{type(exc).__name__}: {exc}"}


def http_bytes(method: str, path: str, payload: dict[str, Any] | None = None,
               timeout: float = 30) -> tuple[bytes, dict[str, str]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(COMFY_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 -- fixed localhost URL
            return response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {path}: {body[:4000]}") from exc


def http_json(method: str, path: str, payload: dict[str, Any] | None = None,
              timeout: float = 30) -> dict[str, Any]:
    body, _ = http_bytes(method, path, payload, timeout)
    if not body:
        return {}
    value = json.loads(body)
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object from {path}")
    return value


def wait_for_comfyui(timeout: float = 240) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            return http_json("GET", "/system_stats", timeout=10)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2)
    raise TimeoutError(f"ComfyUI did not become ready in {timeout:.0f}s: {last_error}")


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", buffering=1) as output:
        output.write(json.dumps(value, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())


def read_integer(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw, 16) if raw.lower().startswith("0x") else int(raw)
    except (OSError, ValueError):
        return None


def read_cpu_ticks() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    values = [int(item) for item in fields]
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        name, value = line.split(":", 1)
        result[name] = int(value.strip().split()[0]) * 1024
    return result


def gpu_metrics() -> dict[str, Any]:
    for device in sorted(Path("/sys/class/drm").glob("card*/device")):
        if read_integer(device / "vendor") != 0x1002:
            continue
        result: dict[str, Any] = {}
        for name in ("gpu_busy_percent", "mem_info_gtt_used", "mem_info_gtt_total"):
            value = read_integer(device / name)
            if value is not None:
                result[name] = value
        return result
    return {}


def thermal_metrics() -> dict[str, Any]:
    temperatures: list[float] = []
    powers: list[float] = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon[0-9]*"):
        for path in hwmon.glob("temp*_input"):
            value = read_integer(path)
            if value is not None and 0 <= value <= 150_000:
                temperatures.append(value / 1000)
        for path in hwmon.glob("power*_average"):
            value = read_integer(path)
            if value is not None and value >= 0:
                powers.append(value / 1_000_000)
    result: dict[str, Any] = {}
    if temperatures:
        result["temperature_max_c"] = max(temperatures)
    if powers:
        result["power_total_w"] = sum(powers)
    return result


def io_counters() -> dict[str, int]:
    network_rx = network_tx = 0
    for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]:
        name, raw = line.split(":", 1)
        if name.strip() == "lo":
            continue
        fields = raw.split()
        network_rx += int(fields[0])
        network_tx += int(fields[8])
    disk_read = disk_write = 0
    for line in Path("/proc/diskstats").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 10 and re.fullmatch(r"(?:nvme\d+n\d+|sd[a-z]+)", fields[2]):
            disk_read += int(fields[5]) * 512
            disk_write += int(fields[9]) * 512
    return {"network_rx_bytes": network_rx, "network_tx_bytes": network_tx,
            "disk_read_bytes": disk_read, "disk_write_bytes": disk_write}


def resolve_container_cgroup() -> Path | None:
    inspect = evidence(["sudo", "-n", "docker", "inspect", "-f", "{{.State.Pid}}", COMFY_CONTAINER])
    try:
        pid = int(inspect["output"].strip())
        relative = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").strip().split("::", 1)[1]
        candidate = Path("/sys/fs/cgroup") / relative.lstrip("/")
        return candidate if candidate.is_dir() else None
    except (OSError, ValueError, IndexError):
        return None


def container_metrics(cgroup: Path | None) -> dict[str, Any]:
    if cgroup is None:
        return {}
    result: dict[str, Any] = {}
    current = read_integer(cgroup / "memory.current")
    peak = read_integer(cgroup / "memory.peak")
    if current is not None:
        result["comfy_container_memory_bytes"] = current
    if peak is not None:
        result["comfy_container_memory_peak_bytes"] = peak
    try:
        stats = {}
        for line in (cgroup / "memory.stat").read_text(encoding="utf-8").splitlines():
            key, value = line.split()
            stats[key] = int(value)
        result["comfy_container_anon_bytes"] = stats.get("anon")
        result["comfy_container_file_bytes"] = stats.get("file")
    except (OSError, ValueError):
        pass
    return result


def read_sample(previous_cpu: tuple[int, int] | None,
                cgroup: Path | None) -> tuple[dict[str, Any], tuple[int, int]]:
    cpu = read_cpu_ticks()
    memory = read_meminfo()
    sample: dict[str, Any] = {
        "recorded_at": utc_now(), "monotonic": time.monotonic(),
        "load_1m": os.getloadavg()[0],
        "memory_total_bytes": memory.get("MemTotal"),
        "memory_available_bytes": memory.get("MemAvailable"),
        "memory_used_bytes": memory.get("MemTotal", 0) - memory.get("MemAvailable", 0),
        "swap_used_bytes": memory.get("SwapTotal", 0) - memory.get("SwapFree", 0),
    }
    if previous_cpu is not None:
        total_delta = cpu[0] - previous_cpu[0]
        idle_delta = cpu[1] - previous_cpu[1]
        if total_delta > 0:
            sample["cpu_busy_percent"] = 100 * (total_delta - idle_delta) / total_delta
    sample.update(gpu_metrics())
    sample.update(thermal_metrics())
    sample.update(io_counters())
    sample.update(container_metrics(cgroup))
    return sample, cpu


SUMMARY_METRICS = (
    "cpu_busy_percent", "load_1m", "memory_used_bytes", "memory_available_bytes",
    "swap_used_bytes", "gpu_busy_percent", "mem_info_gtt_used", "temperature_max_c",
    "power_total_w", "comfy_container_memory_bytes", "comfy_container_memory_peak_bytes",
    "comfy_container_anon_bytes", "comfy_container_file_bytes",
)
COUNTER_METRICS = ("network_rx_bytes", "network_tx_bytes", "disk_read_bytes", "disk_write_bytes")


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"sample_count": len(samples)}
    for metric in SUMMARY_METRICS:
        values = [item[metric] for item in samples if isinstance(item.get(metric), (int, float))]
        if values:
            summary[metric] = {"start": values[0], "end": values[-1], "min": min(values),
                               "max": max(values), "mean": statistics.fmean(values)}
    for metric in COUNTER_METRICS:
        values = [item[metric] for item in samples if isinstance(item.get(metric), int)]
        if values:
            summary[metric] = {"start": values[0], "end": values[-1],
                               "delta": max(0, values[-1] - values[0])}
    return summary


class HostMonitor:
    def __init__(self, path: Path, interval: float) -> None:
        self.path = path
        self.interval = interval
        self.samples: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.cgroup: Path | None = None

    def start(self) -> None:
        self.cgroup = resolve_container_cgroup()
        self.thread = threading.Thread(target=self._loop, name="comfy-resource-monitor", daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        previous_cpu = None
        with self.path.open("a", encoding="utf-8", buffering=1) as output:
            while not self.stop_event.is_set():
                try:
                    sample, previous_cpu = read_sample(previous_cpu, self.cgroup)
                except Exception as exc:
                    sample = {"recorded_at": utc_now(), "monotonic": time.monotonic(),
                              "sample_error": f"{type(exc).__name__}: {exc}"}
                with self.lock:
                    self.samples.append(sample)
                output.write(json.dumps(sample, sort_keys=True) + "\n")
                self.stop_event.wait(self.interval)

    def mark(self) -> int:
        with self.lock:
            return len(self.samples)

    def summary_since(self, marker: int) -> dict[str, Any]:
        with self.lock:
            return summarize_samples(list(self.samples[marker:]))

    def latest(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.samples[-1]) if self.samples else {}

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=max(2, self.interval * 2))


def container_running(name: str) -> bool:
    state = evidence(["sudo", "-n", "docker", "inspect", "-f", "{{.State.Running}}", name])
    return state.get("returncode") == 0 and state.get("output", "").strip() == "true"


def service_active(name: str) -> bool:
    state = evidence(["sudo", "-n", "systemctl", "is-active", "--quiet", name])
    return state.get("returncode") == 0


class RuntimeCoordinator:
    def __init__(self, enabled: bool, log: Callable[[str], None]) -> None:
        self.enabled = enabled
        self.log = log
        self.initial: dict[str, bool] = {}

    def prepare(self) -> None:
        if not self.enabled:
            wait_for_comfyui()
            return
        run_command(["sudo", "-n", "true"])
        self.initial = {name: container_running(name) for name in
                        (COMFY_CONTAINER, LLAMACPP_CONTAINER, OLLAMA_CONTAINER)}
        self.initial.update({name: service_active(name) for name in
                             (LMSTUDIO_SERVICE, LMSTUDIO_TIMER)})
        self.log(f"Captured container state: {self.initial}")
        if not self.initial[COMFY_CONTAINER]:
            run_command(["sudo", "-n", "docker", "start", COMFY_CONTAINER], timeout=180)
        wait_for_comfyui()
        queue = http_json("GET", "/queue")
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise RuntimeError("ComfyUI already has queued work; refusing to disrupt it")
        # Stop the health-check timer before the service so it cannot reload the
        # coding model during a long image run. Stopping the service is more
        # robust than relying on an installation-specific lms CLI path.
        run_command(["sudo", "-n", "systemctl", "stop", LMSTUDIO_TIMER], check=False)
        run_command(["sudo", "-n", "systemctl", "stop", LMSTUDIO_SERVICE], timeout=120, check=False)
        # Stop the other inference containers for repeatable resource measurements.
        for container in (LLAMACPP_CONTAINER, OLLAMA_CONTAINER):
            if self.initial[container]:
                run_command(["sudo", "-n", "docker", "stop", "--time", "30", container], timeout=60)
        http_json("POST", "/free", {"unload_models": True, "free_memory": True}, timeout=30)
        time.sleep(2)

    def restore(self) -> None:
        if not self.enabled or not self.initial:
            return
        self.log("Releasing ComfyUI memory and restoring initial container states")
        with contextlib.suppress(Exception):
            http_json("POST", "/free", {"unload_models": True, "free_memory": True}, timeout=30)
        for container in (LLAMACPP_CONTAINER, OLLAMA_CONTAINER):
            action = "start" if self.initial[container] else "stop"
            evidence(["sudo", "-n", "docker", action, container], timeout=120)
        if self.initial[LMSTUDIO_SERVICE]:
            evidence(["sudo", "-n", "systemctl", "start", LMSTUDIO_SERVICE], timeout=240)
        if self.initial[LMSTUDIO_TIMER]:
            evidence(["sudo", "-n", "systemctl", "start", LMSTUDIO_TIMER], timeout=60)
        if not self.initial[COMFY_CONTAINER]:
            evidence(["sudo", "-n", "docker", "stop", "--time", "30", COMFY_CONTAINER], timeout=60)


def workflow_for(task: ImageTask, filename_prefix: str) -> dict[str, Any]:
    return {
        "3": {"inputs": {"seed": task.seed, "steps": task.steps, "cfg": 1.0,
                           "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
                           "model": ["16", 0], "positive": ["6", 0], "negative": ["7", 0],
                           "latent_image": ["13", 0]}, "class_type": "KSampler"},
        "6": {"inputs": {"text": task.prompt, "clip": ["18", 0]},
               "class_type": "CLIPTextEncode"},
        "7": {"inputs": {"text": task.negative, "clip": ["18", 0]},
               "class_type": "CLIPTextEncode"},
        "8": {"inputs": {"samples": ["3", 0], "vae": ["17", 0]},
               "class_type": "VAEDecode"},
        "9": {"inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]},
               "class_type": "SaveImage"},
        "13": {"inputs": {"width": task.width, "height": task.height, "batch_size": 1},
                "class_type": "EmptySD3LatentImage"},
        "16": {"inputs": {"unet_name": MODEL, "weight_dtype": "default"},
                "class_type": "UNETLoader"},
        "17": {"inputs": {"vae_name": VAE}, "class_type": "VAELoader"},
        "18": {"inputs": {"clip_name": TEXT_ENCODER, "type": "lumina2", "device": "default"},
                "class_type": "CLIPLoader"},
    }


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("output is not a valid PNG header")
    return struct.unpack(">II", data[16:24])


def history_timing(entry: dict[str, Any]) -> dict[str, Any]:
    messages = entry.get("status", {}).get("messages", [])
    timestamps: dict[str, float] = {}
    for message in messages:
        if not isinstance(message, list) or len(message) != 2 or not isinstance(message[1], dict):
            continue
        timestamp = message[1].get("timestamp")
        if isinstance(timestamp, (int, float)):
            timestamps[message[0]] = timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
    started = timestamps.get("execution_start")
    finished = timestamps.get("execution_success") or timestamps.get("execution_error")
    return {"server_execution_start_epoch": started, "server_execution_end_epoch": finished,
            "server_execution_seconds": finished - started if started and finished else None}


def history_errors(entry: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    for message in entry.get("status", {}).get("messages", []):
        if isinstance(message, list) and len(message) == 2 and message[0] in {
                "execution_error", "execution_interrupted"}:
            errors.append({"type": message[0], "detail": message[1]})
    return errors


def wait_for_history(prompt_id: str, timeout: float,
                     heartbeat: Callable[[float], None] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = http_json("GET", f"/history/{urllib.parse.quote(prompt_id)}", timeout=20)
        if prompt_id in history:
            entry = history[prompt_id]
            if entry.get("status", {}).get("completed"):
                return entry
        if heartbeat is not None:
            heartbeat(time.monotonic() - started)
        time.sleep(1)
    raise TimeoutError(f"prompt {prompt_id} did not complete within {timeout:.0f}s")


def output_images(entry: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for node_output in entry.get("outputs", {}).values():
        if isinstance(node_output, dict):
            images.extend(item for item in node_output.get("images", []) if isinstance(item, dict))
    return images


def available_models() -> dict[str, Any]:
    nodes = {}
    for node in ("UNETLoader", "CLIPLoader", "VAELoader", "EmptySD3LatentImage",
                 "KSampler", "SaveImage"):
        nodes[node] = http_json("GET", f"/object_info/{node}")
    def choices(node: str, field: str) -> list[str]:
        try:
            raw = nodes[node][node]["input"]["required"][field][0]
            return [str(item) for item in raw]
        except (KeyError, IndexError, TypeError):
            return []
    discovered = {"diffusion_models": choices("UNETLoader", "unet_name"),
                  "text_encoders": choices("CLIPLoader", "clip_name"),
                  "vae": choices("VAELoader", "vae_name")}
    missing = []
    if MODEL not in discovered["diffusion_models"]:
        missing.append(MODEL)
    if TEXT_ENCODER not in discovered["text_encoders"]:
        missing.append(TEXT_ENCODER)
    if VAE not in discovered["vae"]:
        missing.append(VAE)
    if missing:
        raise RuntimeError(f"required ComfyUI models not available: {', '.join(missing)}")
    return discovered


def system_snapshot() -> dict[str, Any]:
    commands = {
        "uname": ["uname", "-a"],
        "uptime": ["uptime"],
        "memory": ["free", "-b"],
        "disk": ["df", "-h", "/storage"],
        "processes": ["ps", "-eo", "pid,ppid,user,stat,%cpu,%mem,rss,etimes,comm,args", "--sort=-rss"],
        "containers": ["sudo", "-n", "docker", "inspect", COMFY_CONTAINER,
                       LLAMACPP_CONTAINER, OLLAMA_CONTAINER],
        "container_stats": ["sudo", "-n", "docker", "stats", "--no-stream", "--no-trunc",
                            COMFY_CONTAINER, LLAMACPP_CONTAINER, OLLAMA_CONTAINER],
        "rocm": ["rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--showpower", "--json"],
    }
    try:
        stats: dict[str, Any] = http_json("GET", "/system_stats", timeout=10)
    except Exception as exc:
        stats = {"error": f"{type(exc).__name__}: {exc}"}
    return {"recorded_at": utc_now(), "comfyui_system_stats": stats,
            "commands": {name: evidence(command) for name, command in commands.items()}}


def diagnostic_logs(since_epoch: float) -> dict[str, Any]:
    since = str(int(since_epoch))
    return {
        "kernel": evidence(["sudo", "-n", "journalctl", "-k", "--since", f"@{since}",
                            "--no-pager", "-o", "short-iso"], timeout=60),
        "comfyui": evidence(["sudo", "-n", "docker", "logs", "--since", since,
                             COMFY_CONTAINER], timeout=60),
    }


def anomaly_lines(logs: dict[str, Any]) -> list[str]:
    matches = []
    for item in logs.values():
        for line in str(item.get("output", "")).splitlines():
            if ANOMALY_RE.search(line):
                matches.append(line[-2000:])
    return matches[-100:]


def format_bytes(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{value / (1024 ** 3):.1f} GiB"


def make_summary(run_dir: Path, manifest: dict[str, Any], results: list[dict[str, Any]],
                 complete: bool) -> None:
    successful = [item for item in results if item.get("request_ok")]
    summary = {
        "complete": complete, "generated_at": utc_now(), "mode": manifest["mode"],
        "requests": len(results), "successful": len(successful),
        "success_rate": len(successful) / len(results) if results else 0,
        "mean_seconds": statistics.fmean(item["elapsed_seconds"] for item in successful)
        if successful else None,
    }
    write_json(run_dir / "summary.json", summary)
    lines = [
        "# Framework ComfyUI benchmark summary", "",
        f"Status: **{'complete' if complete else 'partial'}**", "",
        f"Mode: `{manifest['mode']}`  ",
        f"Started: `{manifest['started_at']}`  ",
        f"Model: `{MODEL}` with `{TEXT_ENCODER}` and `{VAE}`  ",
        f"Successful requests: **{len(successful)}/{len(results)}**", "",
        "| Task | Category | Size | Steps | Success | Wall time | Server execution | Peak GTT | Peak RAM used | Output |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        resources = item.get("resources", {})
        gtt = resources.get("mem_info_gtt_used", {}).get("max")
        ram = resources.get("memory_used_bytes", {}).get("max")
        output = item.get("output", {}).get("relative_path")
        link = f"[PNG]({output})" if output else "—"
        server = item.get("server_timing", {}).get("server_execution_seconds")
        server_text = f"{server:.1f}s" if isinstance(server, (int, float)) else "—"
        success_text = "yes" if item.get("request_ok") else "no"
        lines.append(
            f"| {item['task']} | {item['category']} | {item['width']}×{item['height']} | "
            f"{item['steps']} | {success_text} | {item['elapsed_seconds']:.1f}s | {server_text} | "
            f"{format_bytes(gtt)} | {format_bytes(ram)} | {link} |"
        )
    lines.extend(["", "## Outputs", ""])
    for item in successful:
        relative = item["output"]["relative_path"]
        lines.extend([f"### {item['task']}", "", item["purpose"], "",
                      f"Prompt: {item['prompt']}", "", f"![{item['task']}]({relative})", ""])
    lines.extend([
        "## Interpretation", "",
        "The first benchmark request follows a full ComfyUI `/free`, so it includes model-load cost; "
        "the second is the comparable warm request. The warm 512/768/1024 rows reuse the same scene and seed. "
        "Quality still needs visual inspection or the rubric in `cloud-evaluation-guide.md`.", "",
        "Raw request records are in `results.jsonl`; one-second telemetry is in `telemetry.jsonl`; "
        "API workflows are in `workflows/`; system and log evidence is under `system-logs/` and `incidents/`.", "",
    ])
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_cloud_guide(run_dir: Path) -> None:
    (run_dir / "cloud-evaluation-guide.md").write_text(
        """# Cloud vision evaluation guide

Evaluate every PNG listed in `evaluation-corpus.jsonl` against its exact prompt and
negative prompt. Return JSONL containing: task, prompt_adherence_0_to_5,
composition_0_to_5, technical_quality_0_to_5, aesthetics_0_to_5,
originality_0_to_5, text_accuracy_0_to_5_or_null, critical_artifacts, and a concise
rationale. Check counts, colors, left/right placement, anatomy, legibility, and
unrequested text explicitly. For `creative_surreal`, reward a novel but coherent
visual idea rather than detail alone. Do not infer quality from runtime or file size.
""", encoding="utf-8")


class Logger:
    def __init__(self, path: Path) -> None:
        self.output = path.open("a", encoding="utf-8", buffering=1)

    def __call__(self, message: str) -> None:
        line = f"{utc_now()} {message}"
        print(line, flush=True)
        self.output.write(line + "\n")

    def close(self) -> None:
        self.output.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "benchmark"), default="benchmark")
    parser.add_argument("--results-root", default=str(DEFAULT_RESULTS_ROOT))
    parser.add_argument("--timeout", type=float, default=1800, help="per-image timeout in seconds")
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--no-manage-runtime-memory", action="store_true",
                        help="do not unload/stop other AI runtimes (measurements may be misleading)")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0 or args.sample_interval <= 0:
        parser.error("timeouts and sample interval must be positive")
    return args


def resolve_results_root(raw: str) -> Path:
    candidate = Path(raw).expanduser().resolve(strict=False)
    allowed = (DEFAULT_RESULTS_ROOT.resolve(),
               (Path.home() / "framework-comfyui-benchmark-results").resolve())
    if not any(candidate == base or candidate.is_relative_to(base) for base in allowed):
        raise ValueError("results root must be below the default /storage path or the user's benchmark-results directory")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def acquire_lock() -> Any:
    runtime_dir = Path("/run/user") / str(os.getuid())
    lock_path = runtime_dir / "framework-comfyui-benchmark.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    lock = os.fdopen(descriptor, "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return lock


class BenchmarkRun:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        root = resolve_results_root(args.results_root)
        self.run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = root / self.run_id
        self.run_dir.mkdir(mode=0o750)
        for name in ("outputs", "workflows", "incidents", "system-logs"):
            (self.run_dir / name).mkdir(mode=0o750)
        self.log = Logger(self.run_dir / "run.log")
        self.started_epoch = time.time()
        self.coordinator = RuntimeCoordinator(not args.no_manage_runtime_memory, self.log)
        self.monitor = HostMonitor(self.run_dir / "telemetry.jsonl", args.sample_interval)
        self.results: list[dict[str, Any]] = []
        self.manifest: dict[str, Any] = {}

    def progress(self, complete: bool = False,
                 active: dict[str, Any] | None = None) -> None:
        value: dict[str, Any] = {"complete": complete, "mode": self.args.mode,
                                 "total_records": len(self.results), "updated_at": utc_now()}
        if active is not None:
            value["active"] = active
        if self.results:
            value["last"] = {key: self.results[-1].get(key) for key in
                             ("task", "category", "request_ok", "elapsed_seconds")}
        write_json(self.run_dir / "progress.json", value)

    def capture_incident(self, task: ImageTask, error: str, since_epoch: float,
                         history: dict[str, Any] | None = None) -> None:
        logs = diagnostic_logs(since_epoch)
        payload = {"captured_at": utc_now(), "task": dataclasses.asdict(task), "error": error,
                   "history": history, "anomalies": anomaly_lines(logs), "logs": logs,
                   "system_snapshot": system_snapshot()}
        write_json(self.run_dir / "incidents" / f"{task.name}.json", payload)

    def run_task(self, task: ImageTask, position: int, total: int) -> dict[str, Any]:
        prefix = f"framework-benchmark/{self.run_id}/{task.name}"
        workflow = workflow_for(task, prefix)
        workflow_path = self.run_dir / "workflows" / f"{task.name}.json"
        write_json(workflow_path, workflow)
        record: dict[str, Any] = {"schema_version": 1, **dataclasses.asdict(task), "task": task.name,
                                  "model": MODEL, "text_encoder": TEXT_ENCODER, "vae": VAE,
                                  "workflow_path": str(workflow_path.relative_to(self.run_dir)),
                                  "started_at": utc_now()}
        self.log(f"[{position}/{total}] {task.name}: {task.width}x{task.height}, {task.steps} steps")
        marker = self.monitor.mark()
        start_epoch = time.time()
        start = time.monotonic()
        history = None
        try:
            queued = http_json("POST", "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())}, timeout=30)
            prompt_id = str(queued["prompt_id"])
            record["prompt_id"] = prompt_id
            record["node_errors"] = queued.get("node_errors", {})
            if record["node_errors"]:
                raise RuntimeError(f"workflow validation errors: {json.dumps(record['node_errors'])[:4000]}")
            next_heartbeat = 0.0
            def report_heartbeat(elapsed: float) -> None:
                nonlocal next_heartbeat
                if elapsed < next_heartbeat:
                    return
                sample = self.monitor.latest()
                active = {"task": task.name, "position": position, "total": total,
                          "stage": "ComfyUI queue active (model loading or generation)",
                          "elapsed_seconds": round(elapsed, 1),
                          "gpu_busy_percent": sample.get("gpu_busy_percent"),
                          "gtt_used_bytes": sample.get("mem_info_gtt_used"),
                          "comfy_container_anon_bytes": sample.get("comfy_container_anon_bytes")}
                self.progress(active=active)
                self.log(f"heartbeat {task.name}: elapsed={elapsed:.0f}s "
                         f"gpu={active['gpu_busy_percent']}% "
                         f"gtt={format_bytes(active['gtt_used_bytes'])} "
                         f"container_anon={format_bytes(active['comfy_container_anon_bytes'])}")
                next_heartbeat = elapsed + 30
            history = wait_for_history(prompt_id, self.args.timeout, report_heartbeat)
            errors = history_errors(history)
            if errors:
                raise RuntimeError(f"ComfyUI execution failed: {json.dumps(errors)[:4000]}")
            images = output_images(history)
            if len(images) != 1:
                raise RuntimeError(f"expected exactly one output image, found {len(images)}")
            image_ref = images[0]
            query = urllib.parse.urlencode({"filename": image_ref["filename"],
                                            "subfolder": image_ref.get("subfolder", ""),
                                            "type": image_ref.get("type", "output")})
            data, headers = http_bytes("GET", f"/view?{query}", timeout=120)
            dimensions = png_dimensions(data)
            if dimensions != (task.width, task.height):
                raise RuntimeError(f"wrong PNG dimensions: expected {(task.width, task.height)}, got {dimensions}")
            if len(data) < 10_000:
                raise RuntimeError(f"suspiciously small PNG: {len(data)} bytes")
            local_path = self.run_dir / "outputs" / f"{task.name}.png"
            local_path.write_bytes(data)
            record["request_ok"] = True
            record["output"] = {"relative_path": str(local_path.relative_to(self.run_dir)),
                                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                "width": dimensions[0], "height": dimensions[1],
                                "content_type": headers.get("Content-Type"), "api_reference": image_ref}
            record["server_timing"] = history_timing(history)
            record["history_status"] = history.get("status")
        except Exception as exc:
            record["request_ok"] = False
            record["error"] = f"{type(exc).__name__}: {exc}"
            self.log(f"ERROR: {record['error']}")
            self.capture_incident(task, record["error"], start_epoch, history)
        record["elapsed_seconds"] = time.monotonic() - start
        record["finished_at"] = utc_now()
        record["resources"] = self.monitor.summary_since(marker)
        self.log(f"result={'ok' if record['request_ok'] else 'failed'} elapsed={record['elapsed_seconds']:.1f}s")
        return record

    def run(self) -> int:
        tasks = smoke_tasks() if self.args.mode == "smoke" else benchmark_tasks()
        self.manifest = {"schema_version": 1, "started_at": utc_now(), "mode": self.args.mode,
                         "comfyui_url": COMFY_URL, "tasks": [dataclasses.asdict(task) for task in tasks],
                         "coverage": {"image_generation": "tested",
                                      "video_generation": "not tested: no video model files installed",
                                      "model_comparison": "not available: one complete image model stack installed"}}
        write_json(self.run_dir / "manifest.json", self.manifest)
        write_cloud_guide(self.run_dir)
        self.progress()
        self.log(f"Run directory: {self.run_dir}")
        self.log(f"Mode: {self.args.mode}; planned images: {len(tasks)}")
        complete = False
        exit_code = 1
        try:
            write_json(self.run_dir / "system-snapshot-before.json", system_snapshot())
            self.coordinator.prepare()
            stats = wait_for_comfyui()
            discovered = available_models()
            self.manifest["system_stats"] = stats
            self.manifest["available_models"] = discovered
            write_json(self.run_dir / "manifest.json", self.manifest)
            self.monitor.start()
            for index, task in enumerate(tasks, 1):
                record = self.run_task(task, index, len(tasks))
                self.results.append(record)
                append_jsonl(self.run_dir / "results.jsonl", record)
                append_jsonl(self.run_dir / "evaluation-corpus.jsonl", {
                    "task": task.name, "category": task.category, "purpose": task.purpose,
                    "prompt": task.prompt, "negative_prompt": task.negative, "seed": task.seed,
                    "image": record.get("output", {}).get("relative_path"),
                    "generation_succeeded": record.get("request_ok"),
                })
                self.progress()
                make_summary(self.run_dir, self.manifest, self.results, False)
                if not record["request_ok"] and self.args.fail_fast:
                    break
            complete = len(self.results) == len(tasks)
            exit_code = 0 if complete and all(item["request_ok"] for item in self.results) else 1
        except Exception as exc:
            self.log(f"FATAL: {type(exc).__name__}: {exc}")
            (self.run_dir / "fatal-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            self.monitor.stop()
            logs = diagnostic_logs(self.started_epoch)
            write_json(self.run_dir / "system-logs" / "run-logs.json", logs)
            write_json(self.run_dir / "system-snapshot-after.json", system_snapshot())
            anomalies = anomaly_lines(logs)
            if anomalies:
                write_json(self.run_dir / "system-logs" / "anomalies.json", anomalies)
                self.log(f"WARNING: found {len(anomalies)} crash/error log signatures")
            self.coordinator.restore()
            write_json(self.run_dir / "system-snapshot-restored.json", system_snapshot())
            make_summary(self.run_dir, self.manifest, self.results, complete)
            self.progress(complete)
            self.log(f"Benchmark finished: {self.run_dir / 'summary.md'}")
            self.log.close()
        return exit_code


def main() -> int:
    args = parse_args()
    try:
        lock = acquire_lock()
    except BlockingIOError:
        print("another ComfyUI benchmark is already running", file=sys.stderr)
        return 2
    with lock:
        return BenchmarkRun(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
