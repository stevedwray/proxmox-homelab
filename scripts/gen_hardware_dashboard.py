#!/usr/bin/env python3
"""Generate terraform/lxc/stacks/monitoring-stack/dashboards/hardware-health.json.

Run from the repo root:  python3 scripts/gen_hardware_dashboard.py
The JSON is committed; this script is the source of truth for its layout.
"""
import json
import pathlib

OUT = pathlib.Path("terraform/lxc/stacks/monitoring-stack/dashboards/hardware-health.json")
DS = {"type": "prometheus", "uid": "VictoriaMetrics"}
SEL = '{job="node_exporter_hw",stack=~"$host"}'

_id = 0


def _next_id():
    global _id
    _id += 1
    return _id


def row(title, y):
    return {"collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
            "id": _next_id(), "panels": [], "title": title, "type": "row"}


def ts(title, expr, legend, unit, x, y, w=12, h=8, vmin=None, vmax=None):
    defaults = {"color": {"mode": "palette-classic"},
                "custom": {"lineWidth": 1, "fillOpacity": 10}, "unit": unit}
    if vmin is not None:
        defaults["min"] = vmin
    if vmax is not None:
        defaults["max"] = vmax
    return {"datasource": DS, "fieldConfig": {"defaults": defaults, "overrides": []},
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "id": _next_id(),
            "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "table",
                                   "placement": "bottom"},
                        "tooltip": {"mode": "multi"}},
            "targets": [{"expr": expr, "legendFormat": legend, "refId": "A"}],
            "title": title, "type": "timeseries"}


def stat(title, expr, legend, unit, x, y, w=6, h=4, steps=None):
    steps = steps or [{"color": "green", "value": None}]
    return {"datasource": DS,
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "thresholds"},
                                         "thresholds": {"mode": "absolute", "steps": steps}},
                            "overrides": []},
            "gridPos": {"h": h, "w": w, "x": x, "y": y}, "id": _next_id(),
            "options": {"colorMode": "background", "graphMode": "none",
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            "targets": [{"expr": expr, "legendFormat": legend, "refId": "A"}],
            "title": title, "type": "stat"}


TEMP_STEPS = [{"color": "green", "value": None}, {"color": "orange", "value": 75},
              {"color": "red", "value": 90}]
LEG = "{{stack}} {{sensor_name}}"

panels = [
    row("Overview", 0),
    stat("Hottest sensor", f"max by (stack) (node_hwmon_temp_celsius{SEL})",
         "{{stack}}", "celsius", 0, 1, w=8, steps=TEMP_STEPS),
    stat("Slowest running fan (non-zero)",
         f"min by (stack) (node_hwmon_fan_rpm{SEL} > 0)", "{{stack}}", "rpm", 8, 1, w=8),
    stat("Pi undervoltage alarm (1 = active)",
         f"max by (stack) (node_hwmon_in_lcrit_alarm{SEL})", "{{stack}}", "none", 16, 1, w=8,
         steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
    row("Temperatures", 5),
    ts("Temperatures", f"node_hwmon_temp_celsius{SEL}", LEG, "celsius", 0, 6, w=24, h=10),
    row("Fans", 16),
    ts("Fan speed", f"node_hwmon_fan_rpm{SEL}", LEG, "rpm", 0, 17, vmin=0),
    ts("Fan PWM duty", f"node_hwmon_pwm{SEL} / 255", LEG, "percentunit", 12, 17,
       vmin=0, vmax=1),
    row("Voltages and power", 25),
    # `scale` label (default 1, set per divider-fed rail) is read as a number
  # by MetricsQL label_value(); VERIFY this live in Phase C before step 07.
  ts("Voltages", f"node_hwmon_in_volts{SEL} * label_value(node_hwmon_in_volts{SEL}, \"scale\")",
     LEG, "volt", 0, 26),
    ts("Power", f"node_hwmon_power_average_watt{SEL}", LEG, "watt", 12, 26, vmin=0),
]

dash = {
    "annotations": {"list": []},
    "description": "Hardware sensors (temperatures, fans, voltages) from node_exporter's hwmon collector, with friendly sensor names applied at scrape time",
    "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "id": None,
    "links": [], "panels": panels, "refresh": "30s", "schemaVersion": 38,
    "tags": ["lab", "hardware"],
    "templating": {"list": [{
        "name": "host", "label": "Host", "type": "query", "datasource": DS,
        "definition": 'label_values(node_hwmon_temp_celsius{job="node_exporter_hw"}, stack)',
        "query": {"query": 'label_values(node_hwmon_temp_celsius{job="node_exporter_hw"}, stack)',
                  "refId": "A"},
        "refresh": 2, "sort": 1, "multi": True, "includeAll": True,
        "allValue": ".+", "current": {}, "hide": 0}]},
    "time": {"from": "now-6h", "to": "now"}, "timepicker": {}, "timezone": "browser",
    "title": "Hardware Health", "uid": "hardware-health", "version": 1,
}

OUT.write_text(json.dumps(dash, indent=2) + "\n")
print(f"wrote {OUT}")
