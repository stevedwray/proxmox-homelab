from agent_framework import tool
from tools.core import with_quota

# async def, not plain def -- see tools/fs.py's top-of-file comment.
@tool
@with_quota
async def think_tool(reflection: str) -> str:
    """Use this to record deliberate thinking / reasoning about the current situation and potentially next steps in a concise way."""
    return f"Reflection recorded: {reflection}"
