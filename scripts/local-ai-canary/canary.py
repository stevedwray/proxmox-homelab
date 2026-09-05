#!/usr/bin/env python3
"""Standing regression canary for the Laguna S 2.1 + Copilot + MCP pipeline.

Everything validated in docs/coding-stack/plan.md (Laguna's reliability on
Ollama, docs-rag-mcp returning correct grounded answers, cve-mcp being
reachable) is a snapshot from whenever it was tested. This project's own
history has repeatedly shown that snapshot silently going stale: Ollama
version bumps, GGUF re-imports, VS Code Copilot Chat updates, and this
repo's own docs drifting have all broken one part of this chain before
without anyone noticing until a real coding session hit it.

This script re-checks a small set of "golden" facts with deterministic,
checkable answers -- not full BFCL/GPQA-style eval, just "is the thing we
already proved works still working." Run it on a schedule (cron/systemd
timer) or ad hoc after any Ollama/VS Code/model change.

Requires: scripts/local-ai-canary/.venv (python3 -m venv .venv && .venv/bin/pip
install mcp httpx), and the ollama-reliability-proxy running locally for
the model-health check (see scripts/ollama-reliability-proxy/README.md).

Exit code is 0 if every check passes, 1 otherwise -- suitable for cron's
own failure-notification behavior (a cron job whose command fails
normally mails its output) without needing extra plumbing here.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
import urllib.request

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

DOCS_RAG_URL = "http://192.168.50.10:8001/mcp"
# Centralized on ai-services-stack since 2026-08-25 (docs/coding-stack/plan.md
# Phase 6) -- was a workstation-local process, now shared with OpenWebUI.
PROXY_URL = "http://192.168.50.11:11435/v1/chat/completions"
MODEL = "laguna-s-2.1:q4_k_m-ctx131k"

# Known-true, stable facts this pipeline should always be able to
# reproduce. Kept deliberately small and unlikely to churn -- these are
# facts about this repo's own settled design decisions, not live infra
# state that changes often (that's a live NetBox-style check, not this
# script's job).
EXPECTED_STACKS_SUBSET = {
    "mcp-utility-stack",
    "harbor-stack",
    "netbox-stack",
    "authentik-stack",
    "portainer-stack",
}


async def check_list_stacks() -> tuple[bool, str]:
    async with streamable_http_client(DOCS_RAG_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("list_stacks", {})
            names = {getattr(c, "text", "") for c in result.content}
            missing = EXPECTED_STACKS_SUBSET - names
            if missing:
                return False, f"list_stacks missing expected stacks: {missing} (got {len(names)} total)"
            return True, f"list_stacks returned {len(names)} stacks, all expected ones present"


async def check_search_docs_allowed_hosts() -> tuple[bool, str]:
    async with streamable_http_client(DOCS_RAG_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_docs",
                {"query": "docs-rag-mcp allowed hosts 127.0.0.1", "k": 5, "stack": "mcp-utility-stack"},
            )
            blob = " ".join(getattr(c, "text", "") for c in result.content)
            if "127.0.0.1:8001" not in blob:
                return False, "search_docs did not surface the known 127.0.0.1:8001 allowed-hosts fact"
            return True, "search_docs correctly surfaced the 127.0.0.1:8001 allowed-hosts fact"


async def check_search_docs_firewall_rule() -> tuple[bool, str]:
    async with streamable_http_client(DOCS_RAG_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_docs",
                {"query": "docs-rag-mcp MikroTik firewall rule 8001 lan pentest_seg", "k": 5, "stack": "mcp-utility-stack"},
            )
            blob = " ".join(getattr(c, "text", "") for c in result.content)
            if "*78" not in blob and "*79" not in blob:
                return False, "search_docs did not surface the known :8001 MikroTik rule IDs (*78/*79)"
            return True, "search_docs correctly surfaced the :8001 MikroTik rule IDs"


def check_model_health() -> tuple[bool, str]:
    """Direct completion through the reliability proxy -- a deterministic
    prompt with an exact expected answer, same shape as Phase 1's own
    validation approach."""
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Reply with only the digit answer to: what is 12 + 30?"}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        PROXY_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            completion = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return False, f"model completion request failed entirely: {e}"

    content = completion.get("choices", [{}])[0].get("message", {}).get("content", "")
    if "42" not in content:
        return False, f"model gave wrong/degenerate answer to a deterministic arithmetic prompt: {content!r}"
    return True, f"model answered a deterministic prompt correctly via the reliability proxy: {content!r}"


CHECKS = [
    ("list_stacks has expected stacks", check_list_stacks),
    ("search_docs surfaces allowed-hosts fact", check_search_docs_allowed_hosts),
    ("search_docs surfaces firewall-rule fact", check_search_docs_firewall_rule),
    ("model answers correctly via reliability proxy", check_model_health),
]


async def run_async_checks():
    results = []
    for name, fn in CHECKS:
        if inspect.iscoroutinefunction(fn):
            try:
                ok, detail = await fn()
            except Exception as e:
                ok, detail = False, f"check raised: {e}"
        else:
            ok, detail = fn()
        results.append((name, ok, detail))
    return results


def main():
    results = asyncio.run(run_async_checks())
    all_ok = True
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
        all_ok = all_ok and ok
    print()
    print("ALL CHECKS PASSED" if all_ok else "ONE OR MORE CHECKS FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
