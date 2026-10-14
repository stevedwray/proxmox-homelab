"""Read-only Wazuh API survey over an SSH tunnel (127.0.0.1:55000) and indexer (19200)."""
import base64
import json
import os
import ssl
import urllib.request

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    return json.load(urllib.request.urlopen(req, context=ctx, timeout=60))


# Wazuh API
basic = base64.b64encode(f"wazuh-wui:{os.environ['WAZUH_API_PASSWORD']}".encode()).decode()
tok = urllib.request.urlopen(
    urllib.request.Request("https://127.0.0.1:55000/security/user/authenticate?raw=true", method="POST",
                           headers={"Authorization": f"Basic {basic}"}),
    context=ctx, timeout=30).read().decode()
H = {"Authorization": f"Bearer {tok}"}
api = "https://127.0.0.1:55000"
agents = get(f"{api}/agents?limit=500&select=id,name,status,version,os.name,os.version,group,lastKeepAlive,node_name", H)["data"]["affected_items"]
print(f"agents: {len(agents)}")
from collections import Counter
print(" status:", Counter(a["status"] for a in agents))
print(" version:", Counter(a.get("version") for a in agents))
print(" os:", Counter((a.get("os") or {}).get("name") for a in agents))
print(" group:", Counter(tuple(a.get("group", [])) for a in agents))
for a in agents:
    if a["status"] != "active":
        print("  NOT ACTIVE:", a["name"], a["status"], a.get("lastKeepAlive"))
info = get(f"{api}/manager/info", H)["data"]["affected_items"][0]
print("manager:", info.get("version"), info.get("compilation_date"))
st = get(f"{api}/manager/status", H)["data"]["affected_items"][0]
print("daemons not running:", [k for k, v in st.items() if v != "running"])
logs = get(f"{api}/manager/logs/summary", H)["data"]["affected_items"][0]
print("manager log summary:", {k: {x: y for x, y in v.items() if x in ("all", "error", "warning")} for k, v in logs.items() if v.get("error") or v.get("warning")})
cfg = get(f"{api}/manager/configuration/validation", H)["data"]["affected_items"][0]
print("config validation:", cfg)

# Indexer
iauth = base64.b64encode(f"admin:{os.environ['WAZUH_INDEXER_ADMIN_PASSWORD']}".encode()).decode()
IH = {"Authorization": f"Basic {iauth}"}
ix = "https://127.0.0.1:19200"
for path in ("_plugins/_ism/policies", "_cat/allocation?v&bytes=m", "_cat/indices/wazuh-states*,wazuh-monitoring*,wazuh-statistics*?v&h=index,docs.count,store.size&s=store.size:desc"):
    try:
        req = urllib.request.Request(f"{ix}/{path}", headers=IH)
        body = urllib.request.urlopen(req, context=ctx, timeout=60).read().decode()
        print(f"-- {path}\n{body[:1500]}")
    except Exception as exc:  # noqa: BLE001
        print(f"-- {path}: {exc}")
