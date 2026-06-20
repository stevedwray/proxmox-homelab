#!/usr/bin/env python3
"""
Fetch recent logs from VictoriaLogs for a named stack and send them to Claude API for analysis.

Usage:
  ./scripts/victorialogs-analyze.py --stack harbor-stack
  ./scripts/victorialogs-analyze.py --stack proxy-stack --limit 500
  ./scripts/victorialogs-analyze.py --stack authentik-stack --url http://192.168.20.12:9428
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

import anthropic

DEFAULT_VICTORIALOGS_URL = "http://192.168.20.12:9428"
DEFAULT_LIMIT = 200
MODEL = "claude-sonnet-4-6"


def fetch_logs(base_url: str, stack: str, limit: int) -> list[dict]:
    query = f'{{stack="{stack}"}} | limit {limit}'
    params = urllib.parse.urlencode({"query": query, "limit": str(limit)})
    url = f"{base_url}/select/logsql/query?{params}"

    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"error: failed to reach VictoriaLogs at {base_url}: {e}", file=sys.stderr)
        sys.exit(1)

    entries = []
    for line in body.strip().splitlines():
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def format_log_block(entries: list[dict]) -> str:
    lines = []
    for e in entries:
        ts = e.get("_time", "")
        msg = e.get("_msg", "")
        container = e.get("container", "")
        prefix = f"[{ts}] [{container}]" if container else f"[{ts}]"
        lines.append(f"{prefix} {msg}")
    return "\n".join(lines)


def analyze(stack: str, log_block: str, entry_count: int) -> str:
    client = anthropic.Anthropic()

    system = (
        "You are a homelab infrastructure analyst. You will be given a sample of recent log lines "
        "from a specific stack in a Proxmox/Docker lab environment. "
        "Identify anomalies, errors, warnings, repeated failures, or anything operationally significant. "
        "Be concise. Skip lines that are routine health checks or noise. "
        "If nothing notable is found, say so briefly."
    )

    user = (
        f"Stack: {stack}\n"
        f"Sample size: {entry_count} log lines\n\n"
        f"```\n{log_block}\n```"
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze VictoriaLogs stream via Claude API")
    parser.add_argument("--stack", required=True, help="Stack label to query (e.g. harbor-stack)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max log lines to fetch")
    parser.add_argument("--url", default=DEFAULT_VICTORIALOGS_URL, help="VictoriaLogs base URL")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("error: ANTHROPIC_API_KEY environment variable is not set", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching up to {args.limit} log lines for stack={args.stack} from {args.url}...")
    entries = fetch_logs(args.url, args.stack, args.limit)
    if not entries:
        print("No log entries returned. Stack may not be sending logs yet.")
        return

    print(f"Fetched {len(entries)} entries. Sending to Claude ({MODEL}) for analysis...")
    log_block = format_log_block(entries)
    analysis = analyze(args.stack, log_block, len(entries))

    print(f"\n--- Analysis: {args.stack} ---\n")
    print(analysis)


if __name__ == "__main__":
    main()
