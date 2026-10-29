"""业务工具（deepagents 自带文件系统 / 待办 / 子 agent 工具之外的自定义能力）。

deepagents 默认已经给主 agent 和所有子 agent 提供了这些内置工具：
    ls / read_file / write_file / edit_file / glob / grep   —— 虚拟文件系统
    write_todos                                             —— 任务规划
    task                                                    —— 调用子 agent

这里放的是「你自己的」工具。新增一个工具只需要：
    1. 用 @tool 装饰一个函数（docstring 会被 LLM 当作工具说明，务必写清楚）；
    2. 加进下面的 ALL_TOOLS 列表。
"""

from __future__ import annotations

import ast
import operator
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool

# --------------------------------------------------------------------------- #
# 1) 计算器：演示「纯函数工具」
# --------------------------------------------------------------------------- #

_ALLOWED_OPERATORS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    """只允许算术表达式，杜绝 eval 带来的任意代码执行。"""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
        return op(_safe_eval(node.operand))
    raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


@tool
def calculator(expression: str) -> str:
    """计算一个数学表达式并返回结果。

    适用于需要精确数值计算的场景（加减乘除、乘方、取模、括号）。
    不要用它做符号运算或单位换算。

    Args:
        expression: 例如 "(12 + 8) * 3 / 5"。
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError) as exc:
        return f"计算失败：{exc}"
    return f"{expression} = {result}"


# --------------------------------------------------------------------------- #
# 2) 当前时间：演示「需要外部信息的工具」
# --------------------------------------------------------------------------- #


@tool
def current_time(tz_offset_hours: int = 8) -> str:
    """获取当前 UTC 时间，以及按指定时区偏移换算后的本地时间。

    Args:
        tz_offset_hours: 相对 UTC 的时区偏移小时数，默认 8（东八区/北京时间）。
    """
    now_utc = datetime.now(timezone.utc)
    offset = int(tz_offset_hours)
    local = now_utc.astimezone(timezone.utc) if offset == 0 else now_utc
    if offset != 0:
        from datetime import timedelta

        local = now_utc + timedelta(hours=offset)
    return (
        f"UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"UTC{offset:+d}: {local.strftime('%Y-%m-%d %H:%M:%S')}"
    )


# --------------------------------------------------------------------------- #
# 3) 知识库检索：演示「如何接入你自己的 RAG / 内部系统」
# --------------------------------------------------------------------------- #


@tool
def search_knowledge_base(query: str, top_k: int = 3) -> str:
    """检索内部知识库，返回与 query 最相关的文档片段。

    当前是占位实现，返回伪造数据以便跑通链路。接真实检索时，
    把 _MOCK_KB 换成你的向量库 / ES / 内部 API 调用即可，
    函数签名和返回格式保持不变。

    Args:
        query: 检索关键词或自然语言问题。
        top_k: 返回的片段数量，默认 3。
    """
    _MOCK_KB = [
        ("部署流程", "本项目使用 uvicorn 启动，SSE 端点位于 /api/chat/stream。"),
        ("子 agent", "子 agent 通过 deepagents 的 task 工具被主 agent 调用，彼此上下文隔离。"),
        ("模型配置", "通过 .env 的 MODEL_PROVIDER 切换 OpenAI / Anthropic / 兼容端点。"),
        ("流式协议", "服务端把 token、工具调用、子 agent 调用统一成结构化 SSE 事件下发。"),
    ]
    hits = [f"[{title}] {text}" for title, text in _MOCK_KB[: max(1, int(top_k))]]
    header = f"检索 “{query}” 命中 {len(hits)} 条（占位数据）："
    return header + "\n" + "\n".join(f"- {h}" for h in hits)


# --------------------------------------------------------------------------- #

ALL_TOOLS = [calculator, current_time, search_knowledge_base]
