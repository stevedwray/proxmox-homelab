"""Unit tests for cse_tasks.py's served-model record (which model answered)."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
sys.path.insert(0, str(Path(__file__).parent))
# Deployed next to cse_tasks.py; in the repo it lives with the playbooks' files.
sys.path.insert(0, str(Path(__file__).parents[3] / "ansible" / "files" / "framework-lock"))

import cse_tasks  # noqa: E402

BASE = "http://framework.gibbsgreatly.xyz:8080/v1"
PROPS = {
    "model_alias": "glm-5.3-flash",
    "model_path": "/mnt/nvme2/models-gguf/glm-5.3-flash/UD-IQ2_XXS-glm5-next/GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf",
    "build_info": "b11309-a4d880fd5",
    "default_generation_settings": {
        "n_ctx": 131072,
        "params": {"temperature": 1.0, "top_k": 40, "top_p": 0.95, "min_p": 0.01,
                   "repeat_penalty": 1.0, "presence_penalty": 0.0, "n_predict": -1},
    },
}


def fake_server(props=PROPS, models_ok=True):
    calls = []

    def get_json(url):
        calls.append(url)
        if url == f"{BASE}/models":
            if not models_ok:
                raise OSError("connection refused")
            return {"data": [{"id": "glm-5.3-flash"}]}
        if url == "http://framework.gibbsgreatly.xyz:8080/props":
            if props is None:
                raise OSError("404")
            return props
        raise AssertionError(f"unexpected url {url}")

    return get_json, calls


class ServedModelTest(unittest.TestCase):
    def test_llama_server_snapshot(self):
        get_json, calls = fake_server()
        snap = cse_tasks._server_snapshot(BASE, "key", get_json=get_json)
        self.assertEqual(calls, [f"{BASE}/models", "http://framework.gibbsgreatly.xyz:8080/props"])
        self.assertEqual(snap["id"], "glm-5.3-flash")
        self.assertEqual(snap["alias"], "glm-5.3-flash")
        self.assertEqual(snap["n_ctx"], 131072)
        self.assertEqual(snap["build"], "b11309-a4d880fd5")
        self.assertEqual(snap["server_sampling"]["min_p"], 0.01)
        self.assertNotIn("n_predict", snap["server_sampling"])

    def test_not_llama_server(self):
        get_json, _ = fake_server(props=None)
        self.assertEqual(cse_tasks._server_snapshot(BASE, "key", get_json=get_json), {"id": "glm-5.3-flash"})

    def test_unreachable(self):
        get_json, _ = fake_server(models_ok=False)
        snap = cse_tasks._server_snapshot(BASE, "key", get_json=get_json)
        self.assertIn("connection refused", snap["error"])
        self.assertNotIn("id", snap)

    def test_header_lines(self):
        get_json, _ = fake_server()
        result = {"served_model": cse_tasks._server_snapshot(BASE, "key", get_json=get_json),
                  "backend_model": "/models/qwen.gguf", "backend_base_url": BASE}
        lines = cse_tasks._model_header_lines(result)
        self.assertEqual(lines[0], "**Model:** glm-5.3-flash (GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf, "
                                   "131,072 ctx, build b11309-a4d880fd5)  ")
        self.assertEqual(lines[1], f"**Endpoint:** {BASE}  ")

    def test_changed_during_run_is_flagged(self):
        result = {"served_model": {"alias": "glm-5.3-flash", "changed_during_run": "qwen3.8-flash-next"},
                  "backend_base_url": BASE}
        self.assertIn("changed during the run to qwen3.8-flash-next", cse_tasks._model_header_lines(result)[0])

    def test_old_runs_fall_back_to_request_name(self):
        result = {"backend_model": "/models/qwen.gguf", "backend_base_url": BASE}
        self.assertEqual(cse_tasks._model_label(result), "/models/qwen.gguf")
        self.assertEqual(cse_tasks._model_header_lines(result)[0], "**Model:** /models/qwen.gguf  ")


if __name__ == "__main__":
    unittest.main()
