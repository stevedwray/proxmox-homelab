from typing import Any, List, Optional
from pydantic import BaseModel, Field

# tools: List[Any], not List[Callable] -- widened 2026-10-02 to admit
# agent_framework's own MCPTool/MCPStreamableHTTPTool instances (Phase 3,
# docs/maltego-integration/README.md). MCPTool has no __call__, so
# Pydantic's Callable validation rejected it outright; ChatAgent itself
# (engine/orchestrator.py's client.as_agent()) already detects MCPTool
# instances in a tools list and manages their connection lifecycle
# automatically via its own AsyncExitStack (confirmed by reading
# agent_framework/_agents.py directly, not assumed) -- no other code
# here needs to change to support it.
class SubAgentConfig(BaseModel):
    name: str = Field(..., description="Name of the subagent without spaces")
    instructions: str = Field(..., description="Instructions for the subagent. Use {date} and {task_name} placeholders.")
    tools: List[Any] = Field(default_factory=list, description="List of tool functions (or agent_framework MCPTool instances) for the subagent")
    sub_agents: List["SubAgentConfig"] = Field(default_factory=list, description="Sub-agents this agent can delegate to. Only these agents will be available via delegate_tasks.")

class AgentBuilder:
    def __init__(self, name: str, description: str, instructions: str, tools: List[Any], sub_agents: Optional[List[SubAgentConfig]] = None):
        self.name = name
        self.description = description
        self.instructions = instructions
        self.tools = tools
        self.sub_agents = sub_agents or []

    def start(self):
        from engine.tui import cli_main
        cli_main(self)
