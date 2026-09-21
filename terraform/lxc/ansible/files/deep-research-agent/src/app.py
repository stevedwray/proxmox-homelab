import warnings
warnings.filterwarnings("ignore", message=".*is experimental and may change.*")

from engine.sdk import AgentBuilder, SubAgentConfig
from tools import (
    read_workspace_file,
    grep_workspace_file,
    list_workspace_files,
    write_workspace_file,
    fetch_url_to_workspace,
    web_search,
    write_todos,
    read_todos,
    think_tool,
)
from prompts import (
    ORCHESTRATOR_INSTRUCTIONS,
    SEARCH_SUBAGENT_INSTRUCTIONS,
    ANALYZER_SUBAGENT_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
import config

# Three-tier deep-research pipeline: Orchestrator -> Searcher -> Analyzer.
# This is Stage A of docs/deep-research/plan.md -- a faithful replication of
# the source design (Donato Capitella's Local Agent Builder video), not a
# homelab-specific redesign. Do not collapse this to two tiers or swap tools
# here; that is a Stage B decision made from Stage A's own measurements.

# 1. Leaf agent: Analyzer -- file reading only, no web access, no delegation.
#    No sub_agents means the engine does not inject delegate_tasks here.
analyzer = SubAgentConfig(
    name="Analyzer",
    instructions=ANALYZER_SUBAGENT_INSTRUCTIONS,
    tools=[read_workspace_file, grep_workspace_file, think_tool],
)

# 2. Middle agent: Searcher -- web search and fetch only, no direct file
#    reading. This forces it to delegate page inspection to the Analyzer
#    rather than reading fetched pages itself.
searcher = SubAgentConfig(
    name="Searcher",
    instructions=SEARCH_SUBAGENT_INSTRUCTIONS,
    tools=[web_search, fetch_url_to_workspace, think_tool],
    sub_agents=[analyzer],
)

# 3. Orchestrator -- task management and report writing only, no web access,
#    no direct file reading beyond listing/writing its own report. It can
#    only delegate to the Searcher, never bypass it to reach the Analyzer.
app = AgentBuilder(
    name=config.APP_TITLE,
    description=config.APP_DESCRIPTION,
    instructions=ORCHESTRATOR_INSTRUCTIONS,
    tools=[write_workspace_file, list_workspace_files, write_todos, read_todos, think_tool],
    sub_agents=[searcher],
)


def cli_main():
    app.start()


if __name__ == "__main__":
    cli_main()
