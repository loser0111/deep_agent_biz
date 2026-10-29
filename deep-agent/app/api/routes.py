"""HTTP 接口层。

    GET    /api/health                     健康检查
    GET    /api/agents                     列出主 agent 可调度的子 agent
    GET    /api/chat/stream?message=&thread_id=      SSE 流式对话（给原生 EventSource 用）
    POST   /api/chat/stream                 SSE 流式对话（JSON body，给 fetch 用）
    POST   /api/chat                        非流式对话（便于脚本/测试）
    DELETE /api/threads/{thread_id}         清空某个会话的历史
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..streaming import stream_agent_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agent"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户这一轮的输入")
    thread_id: str | None = Field(
        default=None, description="会话 ID；不传则新建一个会话（多轮上下文按它隔离）"
    )


def _resolve_thread_id(thread_id: str | None) -> str:
    return thread_id or uuid.uuid4().hex


def _sse_headers() -> dict[str, str]:
    # X-Accel-Buffering 让 Nginx 不缓冲，否则流式会被攒成一坨再吐
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "provider": settings.model_provider,
        "model": settings.model_name,
        "subagents": request.app.state.subagent_names,
    }


@router.get("/agents")
async def list_agents(request: Request) -> dict[str, Any]:
    """给前端渲染「有哪些子 agent 可用」用。"""
    return {"subagents": request.app.state.subagent_specs}


@router.get("/chat/stream")
async def chat_stream_get(
    request: Request,
    message: str = Query(..., min_length=1),
    thread_id: str | None = Query(default=None),
) -> EventSourceResponse:
    """GET 版 SSE：浏览器原生 EventSource 只能发 GET，调试页走这个。"""
    agent = request.app.state.agent
    settings = request.app.state.settings
    tid = _resolve_thread_id(thread_id)

    async def generator():
        async for frame in stream_agent_events(agent, message, tid, settings):
            yield frame

    return EventSourceResponse(
        generator(), headers=_sse_headers(), ping=15000, media_type="text/event-stream"
    )


@router.post("/chat/stream")
async def chat_stream_post(request: Request, payload: ChatRequest) -> EventSourceResponse:
    """POST 版 SSE：正式前端推荐用这个（消息体不受 URL 长度限制）。"""
    agent = request.app.state.agent
    settings = request.app.state.settings
    tid = _resolve_thread_id(payload.thread_id)

    async def generator():
        async for frame in stream_agent_events(agent, payload.message, tid, settings):
            yield frame

    return EventSourceResponse(
        generator(), headers=_sse_headers(), ping=15000, media_type="text/event-stream"
    )


@router.post("/chat")
async def chat(request: Request, payload: ChatRequest) -> dict[str, Any]:
    """非流式版本，方便用 curl / 脚本做冒烟测试。"""
    agent = request.app.state.agent
    tid = _resolve_thread_id(payload.thread_id)
    config = {
        "configurable": {"thread_id": tid},
        "recursion_limit": request.app.state.settings.recursion_limit,
    }
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": payload.message}]}, config=config
    )
    messages = result.get("messages", [])
    content = ""
    if messages:
        last = messages[-1]
        content = getattr(last, "content", str(last))
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
    return {"thread_id": tid, "content": content}


@router.delete("/threads/{thread_id}")
async def delete_thread(request: Request, thread_id: str) -> dict[str, Any]:
    checkpointer = getattr(request.app.state.agent, "checkpointer", None)
    if checkpointer is None:
        return {"deleted": False, "reason": "当前未启用 checkpointer"}

    for method_name in ("adelete_thread", "delete_thread"):
        method = getattr(checkpointer, method_name, None)
        if method is None:
            continue
        result = method(thread_id)
        if hasattr(result, "__await__"):
            await result
        return {"deleted": True, "thread_id": thread_id}

    return {"deleted": False, "reason": "checkpointer 不支持删除会话"}
