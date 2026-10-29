"""把 LangGraph 的 astream_events 归一化成 events.py 里定义的 SSE 事件。

这一层是整个骨架里唯一和「框架内部事件名」耦合的地方。
将来 deepagents / langgraph 升级导致事件结构变化，只需要改这个文件。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ..config import Settings, get_settings
from . import events as ev

logger = logging.getLogger(__name__)

# deepagents 用来派发子 agent 的工具名（不同版本可能叫 task / call_subagent）
_SUBAGENT_TOOL_NAMES = {"task", "call_subagent", "invoke_subagent"}


def _chunk_text(chunk: Any) -> str:
    """从 AIMessageChunk 里取出纯文本增量。

    不同厂商的 content 形态不一样：OpenAI 兼容端点通常是 str，
    Anthropic / 新版 OpenAI 可能是 content block 列表，这里统一处理。
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    return ""


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    content = getattr(message, "content", None)
    if content is None:
        return str(message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text") or "")
        return "".join(parts)
    return str(content)


def _tool_output_text(output: Any) -> str:
    """工具返回值可能是 ToolMessage / dict / 原始值，统一成字符串。"""
    if output is None:
        return ""
    if hasattr(output, "content"):
        return _message_text(output)
    if isinstance(output, dict):
        if "content" in output:
            return _message_text(output["content"])
        return str(output)
    return str(output)


class _RunTracker:
    """跟踪「当前这段事件属于哪个 agent」。

    做法：主 agent 每次通过 task 工具派发子 agent，就记下 task 的 run_id ->
    子 agent 名字。之后凡是 parent_ids 里带着这个 run_id 的事件，
    都归到该子 agent 名下；否则算主 agent 的。
    """

    def __init__(self) -> None:
        self.subagent_by_run: dict[str, str] = {}
        self.tool_meta: dict[str, dict[str, Any]] = {}

    def agent_of(self, event: dict[str, Any]) -> str:
        for parent_id in event.get("parent_ids") or []:
            name = self.subagent_by_run.get(parent_id)
            if name:
                return name
        return "main"

    def register_subagent(self, run_id: str, name: str) -> None:
        self.subagent_by_run[run_id] = name


def _extract_subagent_name(args: Any) -> str:
    if not isinstance(args, dict):
        return "unknown"
    for key in ("subagent_type", "subagent", "agent", "name"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _is_subagent_call(name: str, args: Any) -> bool:
    if name in _SUBAGENT_TOOL_NAMES:
        return True
    # 兜底：有些版本工具名不同，但参数里一定带 subagent_type
    return isinstance(args, dict) and "subagent_type" in args


async def stream_agent_events(
    agent: Any,
    message: str,
    thread_id: str,
    settings: Settings | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """驱动一次 agent 运行，逐个 yield SSE 帧（dict 形式，可直接给 sse-starlette）。

    agent 是 build_agent() 返回的编译图；message 是用户这一轮的输入。
    多轮上下文由 checkpointer 按 thread_id 维护，所以这里只传增量消息。
    """
    settings = settings or get_settings()
    run_id = uuid.uuid4().hex
    started = time.monotonic()
    tracker = _RunTracker()
    ok = True

    yield ev.SSEEvent(
        ev.RUN_START,
        {"run_id": run_id, "thread_id": thread_id, "started_at": int(time.time() * 1000)},
    ).to_sse_dict()

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.recursion_limit,
    }
    inputs = {"messages": [{"role": "user", "content": message}]}

    try:
        async for raw in agent.astream_events(inputs, config=config, version="v2"):
            kind = raw.get("event")
            run = raw.get("run_id", "")
            parent_ids = raw.get("parent_ids") or []
            data = raw.get("data") or {}

            # ---------------- 模型增量 token ----------------
            if kind == "on_chat_model_stream":
                text = _chunk_text(data.get("chunk"))
                if text:
                    yield ev.SSEEvent(
                        ev.TOKEN, {"text": text, "agent": tracker.agent_of(raw)}
                    ).to_sse_dict()
                continue

            # ---------------- 模型整条回复结束 ----------------
            if kind == "on_chat_model_end":
                content = _message_text(data.get("output"))
                if content.strip():
                    yield ev.SSEEvent(
                        ev.MESSAGE,
                        {"agent": tracker.agent_of(raw), "content": ev.truncate(content)},
                    ).to_sse_dict()
                continue

            # ---------------- 工具 / 子 agent 调用开始 ----------------
            if kind == "on_tool_start":
                name = raw.get("name") or "unknown"
                args = data.get("input")
                agent_name = tracker.agent_of(raw)

                if _is_subagent_call(name, args):
                    sub_name = _extract_subagent_name(args)
                    tracker.register_subagent(run, sub_name)
                    description = ""
                    if isinstance(args, dict):
                        description = str(args.get("description") or "")
                    yield ev.SSEEvent(
                        ev.SUBAGENT_START,
                        {
                            "id": run,
                            "name": sub_name,
                            "description": ev.truncate(description, 800),
                            "input": ev.truncate(args),
                        },
                    ).to_sse_dict()
                    continue

                tracker.tool_meta[run] = {"name": name, "args": args, "agent": agent_name}
                yield ev.SSEEvent(
                    ev.TOOL_START,
                    {
                        "id": run,
                        "name": name,
                        "args": ev.truncate(args, 1500),
                        "agent": agent_name,
                    },
                ).to_sse_dict()

                # 待办清单单独再发一份，前端可以直接渲染成 checklist
                if name == "write_todos" and isinstance(args, dict):
                    yield ev.SSEEvent(ev.TODO, {"todos": args.get("todos")}).to_sse_dict()
                continue

            # ---------------- 工具 / 子 agent 调用结束 ----------------
            if kind == "on_tool_end":
                name = raw.get("name") or "unknown"
                output = _tool_output_text(data.get("output"))
                meta = tracker.tool_meta.pop(run, None)

                if run in tracker.subagent_by_run:
                    yield ev.SSEEvent(
                        ev.SUBAGENT_END,
                        {
                            "id": run,
                            "name": tracker.subagent_by_run.pop(run),
                            "output": ev.truncate(output),
                            "ok": True,
                        },
                    ).to_sse_dict()
                    continue

                yield ev.SSEEvent(
                    ev.TOOL_END,
                    {
                        "id": run,
                        "name": name,
                        "output": ev.truncate(output),
                        "ok": True,
                        "agent": (meta or {}).get("agent") or tracker.agent_of(raw),
                    },
                ).to_sse_dict()
                continue

            if kind == "on_tool_error":
                ok = False
                yield ev.SSEEvent(
                    ev.ERROR,
                    {
                        "message": f"工具 {raw.get('name')} 执行失败：{ev.truncate(data.get('error'), 800)}",
                        "recoverable": True,
                    },
                ).to_sse_dict()
                continue

            if kind == "on_chain_error":
                ok = False
                yield ev.SSEEvent(
                    ev.ERROR,
                    {"message": ev.truncate(data.get("error"), 800), "recoverable": False},
                ).to_sse_dict()
                continue

    except Exception as exc:  # noqa: BLE001 - 兜底，保证前端一定收到终止事件
        ok = False
        logger.exception("agent 运行失败")
        yield ev.SSEEvent(
            ev.ERROR, {"message": f"{type(exc).__name__}: {exc}", "recoverable": False}
        ).to_sse_dict()

    yield ev.SSEEvent(
        ev.RUN_END,
        {
            "run_id": run_id,
            "thread_id": thread_id,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "ok": ok,
        },
    ).to_sse_dict()
