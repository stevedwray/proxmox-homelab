"""Read-only Wazuh alert survey over an SSH tunnel to the indexer (127.0.0.1:19200)."""
import base64
import json
import os
import ssl
import urllib.request

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
auth = base64.b64encode(f"admin:{os.environ['WAZUH_INDEXER_ADMIN_PASSWORD']}".encode()).decode()


def search(index, body):
    req = urllib.request.Request(
        f"https://127.0.0.1:19200/{index}/_search",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, context=ctx, timeout=90))


rng = {"range": {"@timestamp": {"gte": "now-24h"}}}
body = {
    "size": 0,
    "query": rng,
    "aggs": {
        "rules": {
            "terms": {"field": "rule.id", "size": 15},
            "aggs": {
                "d": {"terms": {"field": "rule.description", "size": 1}},
                "lvl": {"terms": {"field": "rule.level", "size": 1}},
                "agents": {"cardinality": {"field": "agent.name"}},
            },
        },
        "agents": {"terms": {"field": "agent.name", "size": 30}},
        "levels": {"terms": {"field": "rule.level", "size": 16}},
        "groups": {"terms": {"field": "rule.groups", "size": 14}},
    },
}
d = search("wazuh-alerts-4.x-*", body)
a = d["aggregations"]
print("alerts in 24h:", d["hits"]["total"]["value"])
print("-- top rules (count, id, level, agents, description)")
for b in a["rules"]["buckets"]:
    print(b["doc_count"], b["key"], "L" + str(b["lvl"]["buckets"][0]["key"]), b["agents"]["value"], b["d"]["buckets"][0]["key"][:72])
print("-- by agent:", [(b["key"], b["doc_count"]) for b in a["agents"]["buckets"]])
print("-- by level:", [(b["key"], b["doc_count"]) for b in a["levels"]["buckets"]])
print("-- by group:", [(b["key"], b["doc_count"]) for b in a["groups"]["buckets"]])
