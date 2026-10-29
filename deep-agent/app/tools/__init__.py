"""自定义工具集合。

对外只暴露 ALL_TOOLS，主 agent 与子 agent 默认共享同一份工具列表。
如果某个子 agent 只应该拿到一部分工具，在它的 SubAgentSpec 里显式指定
`tools=[...]` 即可（见 app/agents/subagents/*.py）。
"""

from __future__ import annotations

from .builtin import ALL_TOOLS, calculator, current_time, search_knowledge_base

__all__ = ["ALL_TOOLS", "calculator", "current_time", "search_knowledge_base"]
