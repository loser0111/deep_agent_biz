"""子 agent 注册表。

把「有哪些子 agent」收敛成一个列表，新增/下线子 agent 只改这一处。
每个子 agent 用 SubAgentSpec 描述，最终会被翻译成 deepagents 需要的 dict：

    {"name": ..., "description": ..., "prompt": ..., "tools": [...], "model": ...}

其中 description 非常关键——主 agent 完全靠它来判断「这个任务该不该派给谁」，
所以要写清楚「这个子 agent 擅长什么、什么时候该用它」，而不是写它的内部实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, get_settings
from ..llm import build_chat_model


@dataclass
class SubAgentSpec:
    """一个子 agent 的声明式定义。"""

    name: str
    """主 agent 调用时使用的名字，建议全小写 + 下划线。"""

    description: str
    """给主 agent 看的说明：擅长什么、什么场景该派给它。"""

    prompt: str
    """子 agent 自己的 system prompt。"""

    tools: list[Any] | None = None
    """该子 agent 可用的自定义工具。None 表示继承主 agent 的全部工具。"""

    model_role: str | None = None
    """填 "subagent" 时使用 SUBAGENT_MODEL 指定的模型；None 表示继承主 agent 模型。"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """额外透传给前端的元信息，例如 icon / 展示名。"""

    def to_deepagents_dict(self, settings: Settings | None = None) -> dict[str, Any]:
        settings = settings or get_settings()
        spec: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
        }
        if self.tools is not None:
            spec["tools"] = self.tools
        if self.model_role:
            spec["model"] = build_chat_model(self.model_role, settings)
        return spec

    def to_public_dict(self) -> dict[str, Any]:
        """给 /api/agents 接口用的、可安全序列化的描述。"""
        return {
            "name": self.name,
            "description": self.description,
            "tools": [getattr(t, "name", str(t)) for t in (self.tools or [])],
            "inherits_all_tools": self.tools is None,
            **self.metadata,
        }


class SubAgentRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, SubAgentSpec] = {}

    def register(self, spec: SubAgentSpec) -> SubAgentSpec:
        if spec.name in self._specs:
            raise ValueError(f"子 agent 名字重复: {spec.name}")
        self._specs[spec.name] = spec
        return spec

    def all(self) -> list[SubAgentSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> SubAgentSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs)


registry = SubAgentRegistry()


def load_default_subagents() -> SubAgentRegistry:
    """导入内置的三个示例子 agent 并注册。

    注意导入放在函数内部，避免模块级循环依赖
    （子 agent 模块需要 import registry）。
    """
    from .subagents import coder, researcher, reviewer

    for module in (researcher, coder, reviewer):
        if module.SUBAGENT.name not in registry.names():
            registry.register(module.SUBAGENT)
    return registry
