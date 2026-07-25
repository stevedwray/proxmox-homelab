#!/usr/bin/env python3
"""Write Ollama's loaded-model stats as a node_exporter textfile-collector
file. Run periodically via a systemd timer -- see
ansible/00-initial-setup/framework-desktop-bootstrap.yml.

Ollama has no native Prometheus endpoint (confirmed live: /metrics 404s),
but /api/ps returns real per-loaded-model data -- this polls that and
re-exposes it as a small set of gauges, same textfile-collector mechanism
as the AMDGPU stats script.
"""

import datetime
import json
import os
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/ps"
TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
OUTPUT_FILE = os.path.join(TEXTFILE_DIR, "ollama_stats.prom")


def escape_label(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def expires_in_seconds(expires_at):
    if not expires_at:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = (parsed - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    return max(0, delta)


def fetch_models():
    with urllib.request.urlopen(OLLAMA_URL, timeout=5) as response:
        payload = json.load(response)
    return payload.get("models", [])


def main():
    lines = []
    lines.append("# HELP ollama_scrape_up Whether the last poll of Ollama's /api/ps succeeded")
    lines.append("# TYPE ollama_scrape_up gauge")
    lines.append("# HELP ollama_model_loaded Always 1 for each model Ollama currently has loaded")
    lines.append("# TYPE ollama_model_loaded gauge")
    lines.append("# HELP ollama_model_size_bytes On-disk size of the loaded model")
    lines.append("# TYPE ollama_model_size_bytes gauge")
    lines.append("# HELP ollama_model_vram_bytes VRAM/GTT bytes currently used by the loaded model")
    lines.append("# TYPE ollama_model_vram_bytes gauge")
    lines.append("# HELP ollama_model_context_length Context window configured for the loaded model")
    lines.append("# TYPE ollama_model_context_length gauge")
    lines.append("# HELP ollama_model_expires_in_seconds Seconds until Ollama unloads this model if idle")
    lines.append("# TYPE ollama_model_expires_in_seconds gauge")

    try:
        models = fetch_models()
        lines.append("ollama_scrape_up 1")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        models = []
        lines.append("ollama_scrape_up 0")

    for model in models:
        name = escape_label(model.get("model", "unknown"))
        lines.append(f'ollama_model_loaded{{model="{name}"}} 1')
        lines.append(f'ollama_model_size_bytes{{model="{name}"}} {model.get("size", 0)}')
        lines.append(f'ollama_model_vram_bytes{{model="{name}"}} {model.get("size_vram", 0)}')
        lines.append(f'ollama_model_context_length{{model="{name}"}} {model.get("context_length", 0)}')
        expires_in = expires_in_seconds(model.get("expires_at", ""))
        if expires_in is not None:
            lines.append(f'ollama_model_expires_in_seconds{{model="{name}"}} {expires_in:.0f}')

    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    tmp_path = OUTPUT_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.replace(tmp_path, OUTPUT_FILE)


if __name__ == "__main__":
    main()
