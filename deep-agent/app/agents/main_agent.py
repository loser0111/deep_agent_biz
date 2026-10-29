"""主 agent 的组装。

主 agent 是唯一对外的入口，它自己不做具体活儿，而是：
    规划（write_todos） -> 判断该派给哪个子 agent（task） -> 汇总子 agent 的产出 -> 交付

deepagents 的 create_deep_agent 会把「文件系统 / 待办 / 子 agent 调用」这些能力
自动注入进去，我们只需要提供：模型、自定义工具、system prompt、子 agent 列表。
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from ..config import Settings, get_settings
from ..llm import build_chat_model
from ..tools import ALL_TOOLS
from .registry import SubAgentRegistry, load_default_subagents

logger = logging.getLogger(__name__)

MAIN_SYSTEM_PROMPT = """你是一个主控 agent（orchestrator），负责把用户的需求拆解、分派并最终交付。

## 你的职责边界
你**不**亲自完成具体的调研、编码、评审工作，而是把这些任务派给合适的子 agent。
你的价值在于：拆解任务、选对人、控制节奏、汇总结果。

## 工作流程
1. **先规划**：接到任务后，先用 write_todos 写下待办清单。清单要具体到可执行的动作。
2. **再分派**：对每个待办，判断该由哪个子 agent 承担，用 task 工具派发。
   - 派发时给子 agent 的指令必须自包含：说明目标、已知上下文、期望的输出格式。
   - 子 agent 看不到你和用户的完整对话，所以不要把「如上所述」这类指代丢给它。
3. **可并行就并行**：互不依赖的子任务在同一步里一起派发。
4. **汇总交付**：拿到子 agent 的产出后，整合成一份面向用户的答复。
   - 用户看到的是你写的答复，不是子 agent 的原始输出，所以要消化、去重、组织。
   - 明确说明你做了什么、结论是什么、还有什么不确定。

## 硬性要求
- 简单任务（寒暄、单步问答）不要走上面的流程，直接回答即可，不要为了流程而流程。
- 不要编造子 agent 的产出；子 agent 没查到的信息，如实告诉用户。
- 交付前，如果产出涉及代码或关键决策，派给 reviewer 做一次独立检查。
- 中间产物（长文档、代码、笔记）写进虚拟文件系统，不要把大段原文塞进对话。
"""


def _filter_supported_kwargs(func: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """按目标函数签名裁剪 kwargs，兼容不同 deepagents 版本的参数名差异。

    deepagents 早期版本用 `instructions`，新版本改成 `system_prompt`，
    还可能新增/移除 `checkpointer`、`backend` 等参数。这里统一在调用前裁剪，
    避免因为版本升级直接抛 TypeError。
    """
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return kwargs

    # system_prompt / instructions 是同一个东西的两个名字，只能留一个。
    # 优先认显式签名里存在的那个；两个都不在（例如只有 **kwargs）时，
    # 保守地保留新名字 system_prompt。
    if "system_prompt" in params:
        kwargs.pop("instructions", None)
    elif "instructions" in params:
        kwargs.pop("system_prompt", None)
    else:
        kwargs.pop("instructions", None)

    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs

    filtered = {k: v for k, v in kwargs.items() if k in params}

    dropped = set(kwargs) - set(filtered)
    if dropped:
        logger.warning(
            "当前 deepagents 版本不支持这些参数，已忽略：%s（相关能力会降级，"
            "例如 checkpointer 被忽略时多轮记忆不可用）",
            sorted(dropped),
        )
    return filtered


def build_agent(
    settings: Settings | None = None,
    registry: SubAgentRegistry | None = None,
    checkpointer: Any | None = None,
):
    """构建并返回一个编译好的 deep agent（LangGraph CompiledStateGraph）。

    这个对象支持 astream / astream_events / aget_state，SSE 层直接消费它。
    """
    settings = settings or get_settings()
    registry = registry or load_default_subagents()

    from deepagents import create_deep_agent

    model = build_chat_model("main", settings)
    subagents = [spec.to_deepagents_dict(settings) for spec in registry.all()]

    kwargs: dict[str, Any] = {
        "model": model,
        "tools": ALL_TOOLS,
        # 新版本参数名
        "system_prompt": MAIN_SYSTEM_PROMPT,
        # 旧版本参数名，_filter_supported_kwargs 会按实际签名二选一
        "instructions": MAIN_SYSTEM_PROMPT,
        "subagents": subagents,
    }

    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer

    filtered = _filter_supported_kwargs(create_deep_agent, kwargs)
    logger.info(
        "构建主 agent: provider/model=%s, subagents=%s, params=%s",
        getattr(model, "model_name", getattr(model, "model", "?")),
        [s["name"] for s in subagents],
        sorted(filtered),
    )

    try:
        agent = create_deep_agent(**filtered)
    except TypeError as exc:
        raise RuntimeError(
            f"create_deep_agent 调用失败，可能是 deepagents 版本不兼容：{exc}\n"
            f"当前实际传入的参数：{sorted(filtered)}"
        ) from exc

    # 方便 /api/agents 与前端展示，挂一份元信息在图上（不影响 LangGraph 运行）
    try:
        agent.subagent_specs = [s.to_public_dict() for s in registry.all()]  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - 只影响展示
        pass

    return agent
