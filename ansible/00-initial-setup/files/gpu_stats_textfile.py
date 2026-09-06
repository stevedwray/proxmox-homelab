#!/usr/bin/env python3
"""Write AMDGPU utilization/memory stats as a node_exporter textfile-collector
file. Run periodically via a systemd timer -- see
ansible/00-initial-setup/framework-desktop-bootstrap.yml.

GTT (not VRAM) is the meaningful "GPU memory" figure on this unified-memory
APU: the dedicated VRAM pool is a small fixed carve-out (512MB on this
hardware), while GTT is the shared system-memory pool actually used for
model weights (bounded by the ttm.pages_limit/page_pool_size GRUB tuning
already applied to this host). VRAM is still reported for completeness.
"""

import glob
import os

TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
OUTPUT_FILE = os.path.join(TEXTFILE_DIR, "amdgpu_stats.prom")

SYSFS_FIELDS = {
    "gpu_busy_percent": "amdgpu_busy_percent",
    "mem_info_vram_used": "amdgpu_vram_used_bytes",
    "mem_info_vram_total": "amdgpu_vram_total_bytes",
    "mem_info_gtt_used": "amdgpu_gtt_used_bytes",
    "mem_info_gtt_total": "amdgpu_gtt_total_bytes",
}

HELP_TEXT = {
    "amdgpu_busy_percent": "Current AMDGPU engine utilization percent (0-100)",
    "amdgpu_vram_used_bytes": "Dedicated VRAM currently used -- a small fixed pool on this unified-memory APU, not the real memory ceiling",
    "amdgpu_vram_total_bytes": "Dedicated VRAM total -- a small fixed pool on this unified-memory APU, not the real memory ceiling",
    "amdgpu_gtt_used_bytes": "GTT (shared system memory) currently used by the GPU -- the real memory ceiling for model weights on this hardware",
    "amdgpu_gtt_total_bytes": "GTT (shared system memory) total available to the GPU",
}


def find_card_device_dir():
    candidates = sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"))
    if not candidates:
        return None
    return os.path.dirname(candidates[0])


def read_int(path):
    with open(path, encoding="utf-8") as handle:
        return int(handle.read().strip())


def main():
    lines = []
    lines.append("# HELP amdgpu_scrape_up Whether the last read of AMDGPU sysfs stats succeeded")
    lines.append("# TYPE amdgpu_scrape_up gauge")

    device_dir = find_card_device_dir()
    values = {}
    if device_dir is not None:
        try:
            for sysfs_name, metric_name in SYSFS_FIELDS.items():
                values[metric_name] = read_int(os.path.join(device_dir, sysfs_name))
        except (OSError, ValueError):
            values = {}

    lines.append(f"amdgpu_scrape_up {1 if values else 0}")
    for metric_name in SYSFS_FIELDS.values():
        lines.append(f"# HELP {metric_name} {HELP_TEXT[metric_name]}")
        lines.append(f"# TYPE {metric_name} gauge")
        if metric_name in values:
            lines.append(f"{metric_name} {values[metric_name]}")

    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    tmp_path = OUTPUT_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.replace(tmp_path, OUTPUT_FILE)


if __name__ == "__main__":
    main()
