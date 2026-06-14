"""Unified tool registration — single mount point for all tools."""
from pathlib import Path


def register_all_tools(registry, proposal_dir: Path | None = None):
    """Register all core tools onto the given ToolRegistry.

    Args:
        registry: ToolRegistry singleton.
        proposal_dir: Directory for tool_proposal output. If None, proposals
                      are returned in response but not saved to disk.
    """
    from core.tools.terminal_tool import register_terminal_tool
    from core.tools.web_search_tool import register_web_search_tool, register_tavily_search_tool
    from core.tools.file_tools import register_read_file, register_grep
    from core.tools.tool_proposal import register_tool_proposal, set_proposal_dir
    from core.tools.domain_tool import register_create_domain, set_domain_registry
    from core.tools.kb_tools import register_kb_tools

    register_terminal_tool(registry)
    register_web_search_tool(registry)
    register_tavily_search_tool(registry)
    register_read_file(registry)
    register_grep(registry)
    register_tool_proposal(registry)
    register_create_domain(registry)
    register_kb_tools(registry)

    if proposal_dir:
        set_proposal_dir(proposal_dir)
