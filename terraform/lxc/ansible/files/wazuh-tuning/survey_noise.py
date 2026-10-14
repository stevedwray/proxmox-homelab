"""Read-only: details behind the noisiest rules, plus vulnerability and SCA summaries."""
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
    req = urllib.request.Request(f"https://127.0.0.1:19200/{index}/_search", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, context=ctx, timeout=90))


def terms(index, query, field, size=10, sub=None):
    body = {"size": 0, "track_total_hits": True, "query": query, "aggs": {"t": {"terms": {"field": field, "size": size}}}}
    if sub:
        body["aggs"]["t"]["aggs"] = {"s": {"terms": {"field": sub, "size": 3}}}
    r = search(index, body)
    out = []
    for b in r["aggregations"]["t"]["buckets"]:
        extra = [x["key"] for x in b["s"]["buckets"]] if sub else ""
        out.append((b["doc_count"], b["key"], extra))
    return r["hits"]["total"]["value"], out


day = {"range": {"@timestamp": {"gte": "now-24h"}}}
A = "wazuh-alerts-4.x-*"


def rule(rid):
    return {"bool": {"filter": [day, {"term": {"rule.id": rid}}]}}


print("== total alerts 24h:", search(A, {"size": 0, "track_total_hits": True, "query": day})["hits"]["total"]["value"])
t, o = terms(A, rule("87907"), "agent.name", 5)
print("== 87907 (docker exec_start) by agent:", t, o)
t, o = terms(A, rule("87907"), "data.docker.Actor.Attributes.name", 6)
print("   by container:", o)
t, o = terms(A, rule("87907"), "data.docker.Actor.Attributes.execID", 1)
t, o = terms(A, rule("87907"), "data.docker.Action", 3)
print("   action:", o)
t, o = terms(A, rule("550"), "syscheck.path", 12, "agent.name")
print("== 550 FIM modified by path:", t)
for c, k, e in o:
    print("  ", c, k, e)
t, o = terms(A, rule("2501"), "agent.name", 3)
print("== 2501 auth failure by agent:", o)
t, o = terms(A, rule("2501"), "data.srcip", 5)
print("   by srcip:", o)
t, o = terms(A, rule("510"), "rule.description", 5, "agent.name")
print("== 510 rootcheck:", o[:3])
t, o = terms(A, {"bool": {"filter": [day, {"term": {"rule.id": "5710"}}]}}, "data.srcip", 5)
print("== 5710 non-existent user by srcip:", o)

V = "wazuh-states-vulnerabilities-*"
t, o = terms(V, {"match_all": {}}, "vulnerability.severity", 6)
print("== vulnerabilities total", t, "by severity:", [(c, k) for c, k, _ in o])
t, o = terms(V, {"match_all": {}}, "agent.name", 30)
print("   by agent:", [(k, c) for c, k, _ in o])
t, o = terms(V, {"match_all": {}}, "package.name", 8)
print("   by package:", [(k, c) for c, k, _ in o])
t, o = terms(V, {"match_all": {}}, "vulnerability.id", 5)
print("   top CVE across agents:", [(k, c) for c, k, _ in o])
r = search("wazuh-alerts-4.x-*", {"size": 0, "track_total_hits": True, "query": {"bool": {"filter": [day, {"term": {"rule.groups": "sca"}}]}}})
print("== SCA alerts 24h:", r["hits"]["total"]["value"])
