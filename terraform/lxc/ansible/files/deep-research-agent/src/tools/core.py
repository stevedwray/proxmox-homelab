import contextvars
import functools
import asyncio
import multiprocessing
import queue as queue_module

# Real production incident 2026-09-22: agent_framework itself wraps every
# synchronous (`def`, not `async def`) @tool in asyncio.to_thread() before
# calling it (agent_framework/_tools.py, confirmed by reading its actual
# installed source) -- its own code comments acknowledge this directly:
# "a synchronous tool body already running in a worker thread
# (asyncio.to_thread) cannot be interrupted." Python cannot forcibly kill
# a thread, so any tool whose underlying call can hang (a pathological
# regex an LLM chose against arbitrary fetched content, a stuck native
# library call) can peg the whole container's CPU forever once its own
# asyncio.wait_for gives up -- exactly what happened live. A tool
# declared `async def` bypasses this wrapping entirely (agent_framework
# checks inspect.iscoroutinefunction() and calls it directly), so pairing
# that with running the actually-risky work in a genuinely killable
# subprocess (SIGTERM/SIGKILL, not a thread) closes the gap. Same
# mechanism this repo's tools/web.py already uses for
# fetch_url_to_workspace -- shared here so it isn't duplicated per tool.
_MP_CONTEXT = multiprocessing.get_context("spawn")


async def run_with_hard_kill(target, args: tuple, timeout: float):
    """Runs `target(*args, result_queue)` in a spawned subprocess and
    guarantees it's dead -- via SIGTERM then SIGKILL -- if it doesn't
    finish in time. `target` must be a module-level function (picklable
    for spawn) that puts ("ok", value) or ("error", message) onto the
    queue it receives as its last argument; never raises across the
    process boundary itself. Raises asyncio.TimeoutError on timeout, or
    RuntimeError(message) if the worker reported its own failure.
    """
    result_queue = _MP_CONTEXT.Queue()
    process = _MP_CONTEXT.Process(target=target, args=(*args, result_queue), daemon=True)
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


# --- TOOL QUOTA SYSTEM ---
# Protects local LLM workflows from infinite retry loops (e.g., repeatedly failing to parse a URL)
tool_quotas_ctx = contextvars.ContextVar('tool_quotas', default=None)

class QuotaAbortException(BaseException):
    """Raised when a tool is called repeatedly despite being over quota, indicating an LLM loop."""
    pass

def check_quota(tool_name: str) -> str | None:
    """Check if the specific tool has exceeded its per-invocation quota."""
    ctx = tool_quotas_ctx.get()
    if ctx and tool_name in ctx:
        if ctx[tool_name]["used"] >= ctx[tool_name]["limit"]:
            ctx[tool_name]["used"] += 1
            if ctx[tool_name]["used"] > ctx[tool_name]["limit"] + 3:
                raise QuotaAbortException(f"Agent trapped in loop. Quota exceeded multiple times for {tool_name}.")
            return (
                f"Error: Quota reached. You have used the '{tool_name}' tool "
                f"{ctx[tool_name]['limit']} times out of your limit. "
                f"You MUST summarize what you've done and state clearly that you "
                f"had to stop due to quota limits."
            )
        ctx[tool_name]["used"] += 1
    return None

def _get_tool_rule(tool_name: str, rule_key: str, default_val: int) -> int:
    """Extract custom quota rules (like max_lines) for a specific tool."""
    ctx = tool_quotas_ctx.get()
    if ctx and tool_name in ctx and "rules" in ctx[tool_name]:
        return ctx[tool_name]["rules"].get(rule_key, default_val)
    return default_val

def with_quota(func):
    """Decorator to enforce quotas dynamically based on the function's name and surface full diagnostic tracebacks safely."""
    import traceback
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if err := check_quota(func.__name__): return err
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                return f"CRITICAL TOOL EXECUTION ERROR: {func.__name__} failed internally.\n\nException Details:\n{traceback.format_exc()}"
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if err := check_quota(func.__name__): return err
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return f"CRITICAL TOOL EXECUTION ERROR: {func.__name__} failed internally.\n\nException Details:\n{traceback.format_exc()}"
        return sync_wrapper
