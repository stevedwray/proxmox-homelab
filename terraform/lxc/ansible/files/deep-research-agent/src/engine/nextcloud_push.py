"""Best-effort WebDAV push of a completed run's final_report.md into
Nextcloud, per docs/nextcloud-stack/plan.md Phase 2. Never raises --
final_report.md is already durable on this container's own workspace
volume; Nextcloud being briefly unreachable or a rotated credential
must never fail or block a run that has already completed."""
import base64
import os
import urllib.error
import urllib.request
from pathlib import Path


def push_report_to_nextcloud(run_id: str) -> None:
    webdav_url = os.environ.get("NEXTCLOUD_DR_REPORTS_WEBDAV_URL", "")
    user = os.environ.get("NEXTCLOUD_DR_REPORTS_USER", "")
    password = os.environ.get("NEXTCLOUD_DR_REPORTS_APP_PASSWORD", "")
    if not (webdav_url and user and password):
        return

    from tools.fs import _get_workspace_dir
    report_path = Path(_get_workspace_dir()) / run_id / "final_report.md"
    if not report_path.is_file():
        return

    auth_header = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    base = webdav_url.rstrip("/")
    for collection_url in (f"{base}/deep-research-agent", f"{base}/deep-research-agent/{run_id}"):
        request = urllib.request.Request(collection_url, method="MKCOL")
        request.add_header("Authorization", auth_header)
        try:
            urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code not in (405, 301):
                return
        except urllib.error.URLError:
            return

    put_url = f"{base}/deep-research-agent/{run_id}/final_report.md"
    request = urllib.request.Request(
        put_url, data=report_path.read_bytes(), method="PUT"
    )
    request.add_header("Authorization", auth_header)
    request.add_header("Content-Type", "text/markdown")
    try:
        urllib.request.urlopen(request, timeout=15)
    except (urllib.error.HTTPError, urllib.error.URLError):
        pass
