from tools.core import tool_quotas_ctx, with_quota, QuotaAbortException
from tools.fs import (
    get_workspace_files,
    get_workspace_file_content,
    read_workspace_file,
    write_workspace_file,
    list_workspace_files,
    grep_workspace_file,
    remove_workspace_file
)
from tools.web import fetch_url_to_workspace, web_search
from tools.todos import write_todos, read_todos
from tools.meta import think_tool

# -------------------------------------------------------------
# [!CAUTION] RULES FOR LLM CODING ASSISTANTS EDITING THIS:
# DO NOT define Sub-Agent Delegation functions inside this `tools/` directory!
# Sub-Agent configurations MUST strictly be defined in `src/app.py` directly using the `SubAgentConfig` schema within the `AgentBuilder`.
# The `engine/orchestrator.py` module automatically builds the delegation handlers (`delegate_tasks`) dynamically.
#
# Deep-research customization (Stage A, docs/deep-research/plan.md):
# run_shell_command and the RAG tools (semantic_search, keyword_search,
# list_library_files, read_library_file) were removed here per the skill's
# own CHECKLIST.md ("Shell Tool Pruning" / "RAG Pruning") -- this agent
# never requests shell execution or a document corpus, so neither is wired
# up. tools/shell.py, tools/rag.py, and utils/vectorstore.py are left on
# disk (part of the read-only scaffold reference), just not imported here.
# -------------------------------------------------------------

WORKSPACE_TOOLS = [
    read_workspace_file,
    write_workspace_file,
    list_workspace_files,
    grep_workspace_file,
    fetch_url_to_workspace,
    web_search,
    write_todos,
    read_todos,
    remove_workspace_file,
    think_tool,
]

__all__ = [
    "tool_quotas_ctx",
    "with_quota",
    "QuotaAbortException",
    "WORKSPACE_TOOLS",
    # Individual tools (import these in app.py for selective per-agent tool assignment)
    "read_workspace_file",
    "write_workspace_file",
    "list_workspace_files",
    "grep_workspace_file",
    "remove_workspace_file",
    "fetch_url_to_workspace",
    "web_search",
    "write_todos",
    "read_todos",
    "think_tool",
    # TUI helpers (not agent tools)
    "get_workspace_files",
    "get_workspace_file_content",
]
