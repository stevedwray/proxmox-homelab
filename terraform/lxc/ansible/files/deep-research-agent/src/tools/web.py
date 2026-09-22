import httpx
import multiprocessing
import os
import asyncio
import queue as queue_module
from bs4 import BeautifulSoup
from agent_framework import tool
from tools.core import with_quota
from tools.fs import _get_safe_path, _get_workspace_type, _get_workspace_dir, _IN_MEMORY_FS

# httpx's own timeout= only bounds individual network reads/writes, not the
# whole thread (DNS, redirects, and post-fetch parsing with BeautifulSoup/
# markitdown can all still hang indefinitely). wait_for() is a hard backstop
# so a stuck backend fails the tool call instead of hanging the agent.
_FETCH_TIMEOUT_SECONDS = 45
_SEARCH_TIMEOUT_SECONDS = 30
_TAVILY_API_URL = "https://api.tavily.com/search"

# Real production incident 2026-09-22: a fetch/convert call got stuck
# (root cause not confirmed -- could not reproduce in isolated testing
# despite trying several hypotheses), asyncio.wait_for()'s timeout fired
# and let the agent move on, but the underlying OS thread it had spawned
# via asyncio.to_thread() kept running -- Python cannot forcibly kill a
# thread. That zombie thread pegged the container at 99% CPU for 24+
# minutes with the GPU/LLM completely idle, starving the whole app of
# CPU and freezing the browser session. Running this work in a spawned
# (not forked -- see _fetch_worker's own docstring) subprocess instead
# means a stuck worker can be genuinely SIGKILLed on timeout, not just
# abandoned. "spawn", not the Linux default "fork", because forking a
# process that already has multiple threads/an active asyncio event loop
# risks the child inheriting a lock held by a thread that doesn't exist
# in it -- a different, equally real deadlock class.
_MP_CONTEXT = multiprocessing.get_context("spawn")


def _fetch_worker(url: str, convert_to_md: bool, result_queue) -> None:
    """Module-level (not a closure) so it can be pickled and re-run in a
    fresh spawned interpreter -- see the _MP_CONTEXT comment above for why
    this runs in a subprocess at all. Puts ("ok", data) or ("error", msg)
    onto result_queue; never raises across the process boundary.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)

        if not convert_to_md:
            result_queue.put(("ok", resp.content))  # Raw bytes
            return

        content_type = resp.headers.get("content-type", "").lower()
        # Check actual bytes — a URL might say .pdf but serve HTML (JS-gated doc viewers)
        is_actual_pdf = resp.content[:4] == b"%PDF"
        is_pdf = is_actual_pdf or ("application/pdf" in content_type and is_actual_pdf)

        if is_pdf:
            # Save to temp file, then parse locally
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            try:
                # Try liteparse first (better spatial accuracy for PDFs)
                import shutil
                if shutil.which("liteparse"):
                    import subprocess
                    result = subprocess.run(
                        ["liteparse", tmp_path],
                        capture_output=True, text=True, timeout=60
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        result_queue.put(("ok", result.stdout))
                        return

                # Fallback to markitdown on local file
                try:
                    from utils.parsers import convert_to_markdown
                    md_content = convert_to_markdown(tmp_path)
                    if md_content:
                        result_queue.put(("ok", md_content))
                        return
                except ImportError:
                    pass

                result_queue.put(("ok", f"[ERROR: PDF at {url} could not be parsed. Size: {len(resp.content)} bytes. Try a different source.]"))
            finally:
                os.unlink(tmp_path)
        else:
            # HTML path: try markitdown on local temp file first, then BeautifulSoup fallback
            try:
                from utils.parsers import convert_to_markdown
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="wb") as tmp:
                    tmp.write(resp.content)
                    tmp_path = tmp.name
                try:
                    md_content = convert_to_markdown(tmp_path)
                    if md_content:
                        result_queue.put(("ok", md_content))
                        return
                finally:
                    os.unlink(tmp_path)
            except ImportError:
                pass

            # BeautifulSoup fallback for HTML
            soup = BeautifulSoup(resp.text, "html.parser")
            for script in soup(["script", "style", "nav", "footer"]): script.extract()
            text = '\n'.join(line for line in (l.strip() for l in soup.get_text(separator='\n').splitlines()) if line)
            result_queue.put(("ok", text))
    except Exception as e:
        import traceback
        result_queue.put(("error", f"{e}\n\nTraceback:\n{traceback.format_exc()}"))


async def _fetch_with_hard_kill(url: str, convert_to_md: bool, timeout: float):
    """Runs _fetch_worker in a subprocess and guarantees it's dead -- via
    SIGTERM then SIGKILL -- if it doesn't finish in time. This is the part
    a plain asyncio.wait_for(asyncio.to_thread(...)) cannot do.
    """
    result_queue = _MP_CONTEXT.Queue()
    process = _MP_CONTEXT.Process(target=_fetch_worker, args=(url, convert_to_md, result_queue), daemon=True)
    process.start()
    try:
        status, payload = await asyncio.to_thread(result_queue.get, True, timeout)
    except queue_module.Empty:
        process.terminate()
        await asyncio.to_thread(process.join, 5)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 5)
        raise asyncio.TimeoutError
    else:
        await asyncio.to_thread(process.join, 5)
        if process.is_alive():
            process.kill()
        if status == "error":
            raise RuntimeError(payload)
        return payload


@tool
@with_quota
async def fetch_url_to_workspace(url: str, filename: str, convert_to_md: bool = True) -> str:
    """Fetch external web content and save it directly to the workspace. If convert_to_md is True, parses to Markdown."""
    try:
        try:
            data = await _fetch_with_hard_kill(url, convert_to_md, _FETCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return f"Failed: fetch_url_to_workspace timed out after {_FETCH_TIMEOUT_SECONDS}s fetching '{url}'."

        # Explicitly tag markdown files
        if convert_to_md and not filename.endswith('.md'):
            filename += '.md'

        path = _get_safe_path(filename)
        if not path: return f"Error: Invalid filename '{filename}'."

        if isinstance(data, str):
            chunk = data[:5000000] # Allow larger sizes for markdown text (up to 5MB)
            mode = "w"
            encoding = "utf-8"
        else:
            chunk = data[:5000000] # Cap raw binary at 5MB
            mode = "wb"
            encoding = None

        if _get_workspace_type() == "disk":
            parent_dir = os.path.dirname(path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            if encoding:
                with open(path, mode, encoding=encoding) as f:
                    f.write(chunk)
            else:
                with open(path, mode) as f:
                    f.write(chunk)
            return f"Fetched URL successfully to '{filename}' on disk."
        else:
            _IN_MEMORY_FS[path] = chunk
            return f"Fetched URL successfully to '{filename}' in memory."
    except Exception as e:
        import traceback
        return f"Failed: {e}\n\nTraceback:\n{traceback.format_exc()}"

@tool
async def web_search(
    query: str,
    max_results: int = 5,
    topic: str = "general",
) -> str:
    """Search the web for information on a given query.

    Returns search results with titles, URLs, and snippets.

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return (default: 5)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

    Returns:
        Formatted search results with titles, URLs, and snippets
    """
    from tools.core import check_quota
    quota_error = check_quota("web_search")
    if quota_error:
        return quota_error

    # Real authenticated API, not scraping -- switched 2026-09-22 after
    # confirming live (5 independent methods: DDGS's backend="auto",
    # Playwright/Chromium against Bing and Brave, and raw HTTP against
    # both Bing and DuckDuckGo) that every unauthenticated scraping path
    # is either silently served wrong/irrelevant results (Bing) or
    # explicitly CAPTCHA-gated (DuckDuckGo: "Unfortunately, bots use
    # DuckDuckGo too"). No amount of better parsing or a "more real"
    # browser fixes this -- see docs/deep-research/current-state.md.
    # Free tier: 1000 searches/month, no card required -- see
    # docs/deep-research/current-state.md for current usage expectations.
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "Search failed: TAVILY_API_KEY is not configured."

    async def _do_search():
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "topic": "news" if topic == "news" else "general",
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(_TAVILY_API_URL, json=payload, timeout=_SEARCH_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()

        result_texts = []
        for result in data.get("results", []):
            url = result.get("url", "")
            title = result.get("title", "")
            snippet = result.get("content", "No snippet available")
            result_texts.append(f"## {title}\n**URL:** {url}\n**Snippet:** {snippet}\n")

        return f"🔍 Found {len(result_texts)} result(s) for '{query}':\n\n{chr(10).join(result_texts)}"

    try:
        return await asyncio.wait_for(_do_search(), timeout=_SEARCH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return f"Search failed: timed out after {_SEARCH_TIMEOUT_SECONDS}s for query '{query}'."
    except httpx.HTTPStatusError as e:
        return f"Search failed: Tavily returned {e.response.status_code} for query '{query}'."
    except Exception as e:
        import traceback
        return f"Search failed: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
