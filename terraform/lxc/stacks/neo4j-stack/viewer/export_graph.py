#!/usr/bin/env python3
"""Export the :Homelab graph as the JSON build_graph_view.py reads. Read-only; stdlib only.

Runs on the neo4j host, where the credentials are, and prints JSON to stdout:

    ./with-secrets-prod ssh root@192.168.40.16 'set -a; . /etc/neo4j-import/env; python3 -' \
        < terraform/lxc/stacks/neo4j-stack/viewer/export_graph.py > graph-export.json

(`set -a; . /etc/neo4j-import/env` exports NEO4J_PASSWORD to the process only; it is never printed.)
"""
import base64
import json
import os
import urllib.request

AUTH = base64.b64encode(f"{os.environ.get('NEO4J_USER', 'neo4j')}:{os.environ['NEO4J_PASSWORD']}".encode()).decode()
URL = os.environ.get("NEO4J_URL", "http://127.0.0.1:7474") + "/db/" + os.environ.get("NEO4J_DATABASE", "neo4j") + "/tx/commit"


def query(statement):
    req = urllib.request.Request(URL, data=json.dumps({"statements": [{"statement": statement}]}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Basic " + AUTH})
    payload = json.load(urllib.request.urlopen(req, timeout=120))
    if payload["errors"]:
        raise SystemExit(f"Neo4j error: {payload['errors']}")
    return [r["row"] for r in payload["results"][0]["data"]]


nodes = query("MATCH (n:Homelab) RETURN n.key, [l IN labels(n) WHERE l <> 'Homelab'][0], n.name, n.zone, n.data_classification, "
              "n.trust_level, n.status, n.cluster, n.node, n.protocol, n.ports, n.address, n.vid, n.deployment_tier")
rels = query("MATCH (a:Homelab)-[r]->(b:Homelab) RETURN a.key, b.key, type(r), r.protocol, r.port, r.auth_kind, r.encrypted, "
             "r.crosses_zone, r.from_zone, r.to_zone, r.data_classification, r.trust_boundary_crossing, r.flow_type")
print(json.dumps({"nodes": nodes, "rels": rels}))
