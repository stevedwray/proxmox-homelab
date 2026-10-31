#!/usr/bin/env python3
"""Offline preview: build the graph-export JSON straight from a checkout's
derived threat model, using the neo4j importer's own graph builder. Nothing is
written to NetBox or Neo4j.

    export_from_model.py <repo-with-flows.py> <importer-dir> <out.json>
"""
import json
import sys
from pathlib import Path

repo, importer, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(repo / "terraform/lxc/stacks/netbox-stack/integrations"))
sys.path.insert(0, str(importer))
import flows  # noqa: E402
import neo4j_import  # noqa: E402

graph = neo4j_import.build_graph(flows.build_threat_model(env="pve"), [], [], [], [])
nodes = []
for key, (label, p) in graph.nodes.items():
    nodes.append([key, label, p.get("name"), p.get("zone"), p.get("data_classification"), p.get("trust_level"),
                  p.get("status"), p.get("cluster"), p.get("node"), p.get("protocol"), p.get("ports"),
                  p.get("address"), p.get("vid"), p.get("deployment_tier")])
rels = []
for (rtype, src, dst, _k), p in graph.rels.items():
    rels.append([src, dst, rtype, p.get("protocol"), p.get("port"), p.get("auth_kind"), p.get("encrypted"),
                 p.get("crosses_zone"), p.get("from_zone"), p.get("to_zone"), p.get("data_classification"),
                 p.get("trust_boundary_crossing"), p.get("flow_type")])
Path(out).write_text(json.dumps({"nodes": nodes, "rels": rels}))
print(f"nodes={len(nodes)} rels={len(rels)}")
