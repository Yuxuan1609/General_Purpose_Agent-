"""TB tool registration — replaces terminal/read_file/grep with tmux-backed versions."""
from __future__ import annotations


def register_tb_tools(registry):
    """Register TB-specific tools that override the local versions.

    Only overrides tools that interact with the task environment:
    - terminal → tmux send_keys
    - read_file → tmux sed
    - grep → tmux grep

    Other tools (web_search, kb_query, record_learning, consolidation tools)
    remain unchanged — they run on the host.
    """
    from tb.tools.tb_terminal import register_tb_terminal_tool
    from tb.tools.tb_read_file import register_tb_read_file
    from tb.tools.tb_grep import register_tb_grep

    register_tb_terminal_tool(registry)
    register_tb_read_file(registry)
    register_tb_grep(registry)
