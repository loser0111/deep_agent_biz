"""agent 组装层。

对外暴露：
    build_agent()           构建主 agent（编译好的 LangGraph 图）
    registry                子 agent 注册表
    SubAgentSpec            子 agent 声明式定义
"""

from __future__ import annotations

from .main_agent import MAIN_SYSTEM_PROMPT, build_agent
from .registry import SubAgentRegistry, SubAgentSpec, load_default_subagents, registry

__all__ = [
    "MAIN_SYSTEM_PROMPT",
    "SubAgentRegistry",
    "SubAgentSpec",
    "build_agent",
    "load_default_subagents",
    "registry",
]
