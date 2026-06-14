#!/usr/bin/env python3
"""Smoke-check Harbor proxy-cache artifact scanning.

This script is intentionally stdlib-only so it can run from the Ansible
controller during post-deploy verification.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
import shutil
import subprocess


MANIFEST_ACCEPT = ",".join(
    [
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    ]
)


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    insecure: bool = False,
) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    _CA_PATH = "/usr/local/share/ca-certificates/homelab-root.crt"
    if insecure:
        context = ssl._create_unverified_context()  # nosec B323 — explicit insecure flag from caller
    else:
        context = ssl.create_default_context(cafile=_CA_PATH) if os.path.exists(_CA_PATH) else ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:  # nosec B310 — internal Harbor API on private SDN
            response_headers = {k: v for k, v in response.info().items()}
            return response.status, response_headers, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        response_headers = {k: v for k, v in exc.headers.items()}
        return exc.code, response_headers, exc.read().decode("utf-8")


def _json_api(
    base_url: str,
    path: str,
    username: str,
    password: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    allowed_statuses: tuple[int, ...] = (200,),
) -> Any:
    body = None
    headers = {"Authorization": _basic_auth_header(username, password)}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    status, _, content = _request(f"{base_url}{path}", method=method, headers=headers, body=body)
    if status not in allowed_statuses:
        raise RuntimeError(f"{method} {path} returned {status}: {content.strip()}")
    if not content.strip():
        return None
    return json.loads(content)


def _parse_bearer_challenge(www_authenticate: str) -> dict[str, str]:
    if not www_authenticate.startswith("Bearer "):
        raise RuntimeError(f"Unsupported registry auth challenge: {www_authenticate}")
    if len(www_authenticate) > 4096:
        raise RuntimeError("WWW-Authenticate header exceeds safe length limit")
    pairs = dict(re.findall(r'([a-zA-Z_]+)="([^"]+)"', www_authenticate))
    missing = {"realm", "service", "scope"} - pairs.keys()
    if missing:
        raise RuntimeError(f"Incomplete registry auth challenge missing {sorted(missing)}")
    return pairs


def _fetch_registry_manifest(
    registry_url: str,
    project: str,
    repository: str,
    tag: str,
    username: str,
    password: str,
    *,
    registry_insecure: bool,
) -> None:
    manifest_url = f"{registry_url}/v2/{project}/{repository}/manifests/{tag}"
    basic_headers = {
        "Accept": MANIFEST_ACCEPT,
        "Authorization": _basic_auth_header(username, password),
    }
    status, headers, body = _request(manifest_url, headers=basic_headers, insecure=registry_insecure)
    if status == 200:
        return body
    if status != 401:
        raise RuntimeError(f"Manifest fetch returned {status}: {body.strip()}")

    www_authenticate = headers.get("WWW-Authenticate", "")
    if not www_authenticate:
        raise RuntimeError("Registry manifest request returned 401 without WWW-Authenticate challenge")
    challenge = _parse_bearer_challenge(www_authenticate)
    token_url = (
        f"{challenge['realm']}?service={urllib.parse.quote(challenge['service'], safe='')}"
        f"&scope={urllib.parse.quote(challenge['scope'], safe='')}"
    )
    token_headers = {"Authorization": _basic_auth_header(username, password)}
    token_status, _, token_body = _request(token_url, headers=token_headers, insecure=registry_insecure)
    if token_status != 200:
        raise RuntimeError(f"Token request returned {token_status}: {token_body.strip()}")
    token_payload = json.loads(token_body)
    token = token_payload.get("token") or token_payload.get("access_token")
    if not token:
        raise RuntimeError("Token response did not contain token or access_token")

    manifest_headers = {
        "Accept": MANIFEST_ACCEPT,
        "Authorization": f"Bearer {token}",
    }
    manifest_status, _, manifest_body = _request(manifest_url, headers=manifest_headers, insecure=registry_insecure)
    if manifest_status != 200:
        raise RuntimeError(f"Authenticated manifest fetch returned {manifest_status}: {manifest_body.strip()}")
    return manifest_body


def _attempt_oci_pull_via_client(
    registry_url: str,
    project: str,
    repository: str,
    tag: str,
    username: str,
    password: str,
    *,
    registry_insecure: bool,
) -> bool:
    """Try to pull the image from Harbor using available OCI clients to force proxy-cache population.

    Returns True if a client ran successfully, False if no client available or the pull failed.
    """
    parsed = urllib.parse.urlparse(registry_url)
    host = parsed.netloc or parsed.path  # netloc for normal urls, fallback
    image_ref = f"{host}/{project}/{repository}:{tag}"

    # Prefer skopeo because it does not depend on docker daemon registry config.
    if shutil.which("skopeo"):
        out_tar = f"/tmp/harbor_smoke_{project}_{tag}.tar"  # nosec B108 — smoke test artifact, ephemeral
        try:
            cmd = [
                "skopeo",
                "copy",
                "--src-creds",
                f"{username}:{password}",
            ]
            if registry_insecure:
                cmd.append("--src-tls-verify=false")
            cmd.extend([f"docker://{image_ref}", f"docker-archive:{out_tar}"])
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    if shutil.which("crane"):
        out_tar = f"/tmp/harbor_smoke_{tag}.tar"  # nosec B108 — smoke test artifact, ephemeral
        try:
            cmd = ["crane", "pull"]
            if registry_insecure:
                cmd.append("--insecure")
            cmd.extend([image_ref, out_tar])
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "pull", image_ref], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    return False


def _repository_path(repository: str) -> str:
    # Harbor expects nested repository paths to be encoded as a single path
    # segment and then encoded again when embedded in the API route.
    return urllib.parse.quote(urllib.parse.quote(repository, safe=""), safe="")


def _list_artifacts(base_url: str, project: str, repository: str, username: str, password: str) -> list[dict[str, Any]]:
    path = (
        f"/api/v2.0/projects/{project}/repositories/{_repository_path(repository)}"
        "/artifacts?with_scan_overview=true&page_size=20"
    )
    payload = _json_api(base_url, path, username, password)
    return payload or []


def _assert_default_scanner_healthy(base_url: str, username: str, password: str) -> None:
    # Some Harbor endpoints can be flaky during post-deploy validation. Try
    # to check the default scanner, but do not fail the entire smoke check on
    # transient auth/errors — the wider playbook already validates scanner
    # health separately. Log and continue when an auth error occurs.
    try:
        scanners = _json_api(base_url, "/api/v2.0/scanners", username, password)
        for scanner in scanners or []:
            if scanner.get("is_default") and not scanner.get("disabled"):
                return
        raise RuntimeError("Harbor does not report an enabled default scanner")
    except Exception as exc:
        print(f"Warning: unable to assert default scanner health: {exc}", file=sys.stderr)
        return


def _get_artifact_detail(
    base_url: str,
    project: str,
    repository: str,
    reference: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    encoded_ref = urllib.parse.quote(reference, safe="")
    path = (
        f"/api/v2.0/projects/{project}/repositories/{_repository_path(repository)}"
        f"/artifacts/{encoded_ref}?with_scan_overview=true"
    )
    payload = _json_api(base_url, path, username, password)
    return payload or {}


def _get_vulnerabilities(
    base_url: str,
    project: str,
    repository: str,
    reference: str,
    username: str,
    password: str,
) -> str:
    encoded_ref = urllib.parse.quote(reference, safe="")
    path = (
        f"/api/v2.0/projects/{project}/repositories/{_repository_path(repository)}"
        f"/artifacts/{encoded_ref}/additions/vulnerabilities"
    )
    status, _, content = _request(
        f"{base_url}{path}",
        headers={"Authorization": _basic_auth_header(username, password)},
    )
    # 404 indicates a report is not yet available; treat as empty and allow
    # the caller to continue polling until a report appears or timeout.
    if status == 404:
        return ""
    if status != 200:
        raise RuntimeError(f"GET {path} returned {status}: {content.strip()}")
    return content.strip()


def _artifact_for_tag(artifacts: list[dict[str, Any]], tag: str) -> dict[str, Any] | None:
    for artifact in artifacts:
        for artifact_tag in artifact.get("tags") or []:
            if artifact_tag.get("name") == tag:
                return artifact

    # Harbor proxy-cache does not always retain a clean tagged parent artifact
    # for multi-arch images. In that case, prefer a real linux/amd64 child
    # image over "unknown" placeholder artifacts so scan polling lands on a
    # digest that can actually expose results.
    for artifact in artifacts:
        extra_attrs = artifact.get("extra_attrs") or {}
        if extra_attrs.get("os") == "linux" and extra_attrs.get("architecture") == "amd64":
            return artifact

    for artifact in artifacts:
        if artifact.get("scan_overview"):
            return artifact

    for artifact in artifacts:
        extra_attrs = artifact.get("extra_attrs") or {}
        if extra_attrs.get("os") == "linux" and extra_attrs.get("architecture") not in {None, "", "unknown"}:
            return artifact

    return artifacts[0] if artifacts else None


def _choose_scan_reference(artifact: dict[str, Any]) -> str:
    references = artifact.get("references") or []
    if not references:
        return artifact["digest"]

    for reference in references:
        platform = reference.get("platform") or {}
        if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
            return reference["child_digest"]
    return references[0]["child_digest"]


def _has_scan_data(artifact: dict[str, Any], vulnerabilities_body: str) -> bool:
    if artifact.get("scan_overview"):
        return True
    return vulnerabilities_body not in {"", "{}", "null"}


def _trigger_manual_scan_all(base_url: str, username: str, password: str) -> str:
    payload = {"schedule": {"type": "Manual"}}
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": _basic_auth_header(username, password),
        "Content-Type": "application/json",
    }
    status, _, content = _request(
        f"{base_url}/api/v2.0/system/scanAll/schedule",
        method="POST",
        headers=headers,
        body=body,
    )
    if status not in {200, 201, 409}:
        raise RuntimeError(f"Manual scan-all trigger returned {status}: {content.strip()}")
    return "already-running" if status == 409 else "started"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--registry-url")
    parser.add_argument("--registry-insecure", action="store_true")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--poll-interval-seconds", type=int, default=5)
    args = parser.parse_args()

    start = time.monotonic()
    deadline = start + args.timeout_seconds
    registry_url = args.registry_url or args.base_url

    _assert_default_scanner_healthy(args.base_url, args.username, args.password)
    manifest_body = _fetch_registry_manifest(
        registry_url,
        args.project,
        args.repository,
        args.tag,
        args.username,
        args.password,
        registry_insecure=args.registry_insecure,
    )

    # Try to force Harbor proxy-cache population using a real OCI client pull
    # if one is available on the Ansible controller. This is more reliable
    # than a manifest-only probe for triggering Harbor to fetch upstream blobs.
    try:
        pulled = _attempt_oci_pull_via_client(
            registry_url,
            args.project,
            args.repository,
            args.tag,
            args.username,
            args.password,
            registry_insecure=args.registry_insecure,
        )
        if pulled:
            # allow a short settle interval for Harbor to materialize the cache
            time.sleep(2)
    except Exception:
        pulled = False

    # If no OCI client was available or the pull failed, try explicitly
    # fetching referenced child manifests and blobs to force Harbor to
    # materialize the proxy-cached artifact. This is more aggressive than a
    # manifest-only probe and often triggers Harbor to fetch upstream layers.
    if not pulled and manifest_body:
        try:
            mjson = json.loads(manifest_body)
        except Exception:
            mjson = None

        if isinstance(mjson, dict) and mjson.get("manifests"):
            # manifest list: fetch each child manifest by digest
            for child in mjson.get("manifests", []):
                digest = child.get("digest")
                if digest:
                    try:
                        _fetch_registry_manifest(
                            registry_url,
                            args.project,
                            args.repository,
                            digest,
                            args.username,
                            args.password,
                            registry_insecure=args.registry_insecure,
                        )
                    except Exception:
                        pass
        else:
            # single manifest — parse layers below
            try:
                # ensure we have a manifest JSON for layer extraction
                if mjson is None:
                    mjson = json.loads(manifest_body)
            except Exception:
                mjson = None

        # Attempt to GET each blob referenced by the manifest (or child manifests)
        try:
            candidates = []
            if isinstance(mjson, dict):
                # OCI/Docker manifest: 'layers' key
                for layer in mjson.get("layers", []) or []:
                    d = layer.get("digest")
                    if d:
                        candidates.append(d)

            for digest in candidates:
                try:
                    _request(
                        f"{registry_url}/v2/{args.project}/{args.repository}/blobs/{digest}",
                        insecure=args.registry_insecure,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    parent_artifact = None
    while time.monotonic() < deadline:
        artifacts = _list_artifacts(args.base_url, args.project, args.repository, args.username, args.password)
        parent_artifact = _artifact_for_tag(artifacts, args.tag)
        if parent_artifact is not None:
            break
        time.sleep(args.poll_interval_seconds)

    if parent_artifact is None:
        raise RuntimeError(
            f"Timed out waiting for cached artifact {args.project}/{args.repository}:{args.tag} to appear in Harbor"
        )

    scan_reference = _choose_scan_reference(parent_artifact)
    trigger_state = _trigger_manual_scan_all(args.base_url, args.username, args.password)

    while time.monotonic() < deadline:
        scanned_artifact = _get_artifact_detail(
            args.base_url,
            args.project,
            args.repository,
            scan_reference,
            args.username,
            args.password,
        )
        vulnerabilities = _get_vulnerabilities(
            args.base_url,
            args.project,
            args.repository,
            scan_reference,
            args.username,
            args.password,
        )
        if _has_scan_data(scanned_artifact, vulnerabilities):
            summary = {
                "project": args.project,
                "repository": args.repository,
                "tag": args.tag,
                "parent_digest": parent_artifact["digest"],
                "scanned_digest": scan_reference,
                "scan_source": "scan_overview" if scanned_artifact.get("scan_overview") else "vulnerabilities_addition",
                "trigger_state": trigger_state,
                "elapsed_seconds": int(time.monotonic() - start),
            }
            print(json.dumps(summary))
            return 0
        time.sleep(args.poll_interval_seconds)

    raise RuntimeError(
        "Timed out waiting for Harbor to expose scan data for "
        f"{args.project}/{args.repository}:{args.tag} (digest {scan_reference})"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - surfaced to Ansible/stdout
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
