import json
import struct
import tempfile
import unittest
from pathlib import Path

import comfyui_benchmark as benchmark


class WorkflowTests(unittest.TestCase):
    def test_workflow_uses_task_parameters_and_known_model_stack(self):
        task = benchmark.smoke_tasks()[0]
        workflow = benchmark.workflow_for(task, "test/prefix")
        self.assertEqual(workflow["3"]["inputs"]["seed"], task.seed)
        self.assertEqual(workflow["3"]["inputs"]["steps"], 4)
        self.assertEqual(workflow["13"]["inputs"]["width"], 512)
        self.assertEqual(workflow["16"]["inputs"]["unet_name"], benchmark.MODEL)
        self.assertEqual(workflow["18"]["inputs"]["type"], "lumina2")
        self.assertEqual(workflow["9"]["inputs"]["filename_prefix"], "test/prefix")

    def test_benchmark_matrix_has_expected_coverage(self):
        tasks = benchmark.benchmark_tasks()
        self.assertEqual(len(tasks), 8)
        self.assertEqual({task.width for task in tasks[:4]}, {512, 768, 1024})
        self.assertIn("creativity", {task.category for task in tasks})
        self.assertEqual(len({task.name for task in tasks}), len(tasks))
        self.assertEqual(len({task.seed for task in tasks[1:4]}), 1)
        self.assertNotEqual(tasks[0].seed, tasks[1].seed)


class ParsingTests(unittest.TestCase):
    def test_png_dimensions(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 768, 512)
        self.assertEqual(benchmark.png_dimensions(data), (768, 512))

    def test_png_dimensions_rejects_non_png(self):
        with self.assertRaises(ValueError):
            benchmark.png_dimensions(b"not a png")

    def test_history_timing_accepts_millisecond_timestamps(self):
        entry = {"status": {"messages": [
            ["execution_start", {"timestamp": 1_800_000_000_000}],
            ["execution_success", {"timestamp": 1_800_000_012_500}],
        ]}}
        timing = benchmark.history_timing(entry)
        self.assertEqual(timing["server_execution_seconds"], 12.5)

    def test_output_images_collects_save_node_images(self):
        entry = {"outputs": {"9": {"images": [{"filename": "x.png", "type": "output"}]}}}
        self.assertEqual(benchmark.output_images(entry)[0]["filename"], "x.png")

    def test_resource_summary_reports_max_and_counter_delta(self):
        summary = benchmark.summarize_samples([
            {"gpu_busy_percent": 10, "disk_read_bytes": 100},
            {"gpu_busy_percent": 90, "disk_read_bytes": 500},
        ])
        self.assertEqual(summary["gpu_busy_percent"]["max"], 90)
        self.assertEqual(summary["disk_read_bytes"]["delta"], 400)

    def test_monitor_latest_is_empty_before_sampling(self):
        monitor = benchmark.HostMonitor(Path("unused"), 1.0)
        self.assertEqual(monitor.latest(), {})

    def test_evaluation_corpus_values_are_json_serializable(self):
        task = benchmark.benchmark_tasks()[-1]
        json.dumps({"task": task.name, "prompt": task.prompt, "seed": task.seed})

    def test_summary_accepts_real_record_shape(self):
        task = benchmark.smoke_tasks()[0]
        record = {"schema_version": 1, **task.__dict__, "task": task.name,
                  "request_ok": True, "elapsed_seconds": 2.0,
                  "server_timing": {"server_execution_seconds": 1.5},
                  "resources": {}, "output": {"relative_path": "outputs/test.png"}}
        with tempfile.TemporaryDirectory() as directory:
            benchmark.make_summary(Path(directory), {"mode": "smoke", "started_at": "now"},
                                   [record], True)
            self.assertIn("functional_512", (Path(directory) / "summary.md").read_text())


if __name__ == "__main__":
    unittest.main()
