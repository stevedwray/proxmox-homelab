# SPDX-License-Identifier: AGPL-3.0-or-later
"""Custom engine for the real Google Custom Search JSON API.

Not the same as SearXNG's built-in `google_cse` engine (kept disabled in
this stack's settings.yml) -- that one is hardcoded to a shared
third-party CSE token (`partner-pub-8993703457585266:4862972284`,
blackle.com) and silently ignores any api_key/cx set in settings.yml.
Confirmed by reading both the deployed image's source and upstream
SearXNG's current master branch -- no version implements the real
`googleapis.com/customsearch` endpoint. This module does, using a real
Google Cloud API key and a Programmable Search Engine ID (cx). See
docs/design/lessons-learned.md's SearXNG section.

Configuration
=============

  - name: google-curated
    engine: google_customsearch
    api_key: 'YOUR-API-KEY'   # required
    cx: 'YOUR-CSE-ID'         # required
"""

import typing as t
from urllib.parse import urlencode

from searx.exceptions import SearxEngineAPIException, SearxEngineTooManyRequestsException
from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://programmablesearchengine.google.com/",
    "wikidata_id": "Q2233943",
    "official_api_documentation": "https://developers.google.com/custom-search/v1/overview",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

api_key: str = ""
"""Google Cloud API key with the Custom Search API enabled (required)."""

cx: str = ""
"""Programmable Search Engine ID (required)."""

categories = ["general", "web"]
paging = True
max_page = 10  # API caps at 100 total results, 10 per page
safesearch = True

base_url = "https://www.googleapis.com/customsearch/v1"

results_per_page = 10  # API max per request


def init(_):
    """Validate required settings before the engine is used."""
    if not api_key or not cx:
        raise SearxEngineAPIException("google_customsearch requires both api_key and cx")


def request(query: str, params: "OnlineParams") -> None:
    """Build the Custom Search API request."""
    args: dict[str, str | int] = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": results_per_page,
        "start": (params["pageno"] - 1) * results_per_page + 1,
    }
    if params["safesearch"]:
        args["safe"] = "active"

    params["url"] = f"{base_url}?{urlencode(args)}"


def response(resp: "SXNG_Response") -> EngineResults:
    """Parse the Custom Search API response."""
    res = EngineResults()
    data = resp.json()

    if error := data.get("error"):
        message = error.get("message", "unknown error")
        if error.get("code") == 429:
            raise SearxEngineTooManyRequestsException(message=f"google_customsearch: {message}")
        raise SearxEngineAPIException(f"google_customsearch: {message}")

    for item in data.get("items", []):
        res.add(
            res.types.MainResult(
                url=item["link"],
                title=item.get("title", ""),
                content=item.get("snippet", ""),
            ),
        )

    return res
