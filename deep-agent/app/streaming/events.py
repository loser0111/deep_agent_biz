"""SSE 事件契约。

后端把 LangGraph 五花八门的事件统一成下面这几种，前端只需要认这几种，
后端换框架 / 升级 deepagents 时前端不用改。

事件列表（event 名 -> data 结构）：

    run_start       {run_id, thread_id, started_at}
    token           {text, agent}                     增量 token，agent 标识来自谁
    tool_start      {id, name, args, agent}
    tool_end        {id, name, output, ok, agent}
    subagent_start  {id, name, description, input}     主 agent 派发子 agent
    subagent_end    {id, name, output, ok}
    todo            {todos}                            主 agent 更新了待办清单
    message         {agent, content}                  某条完整回复（落库/校对用）
    error           {message, recoverable}
    run_end         {run_id, elapsed_ms, ok}

约定：
- 每个 run 以 run_start 开始、以 run_end 结束；run_end 一定会在连接关闭前发出。
- 出现不可恢复错误时，先发 error 再发 run_end(ok=false)。
- 大字段（工具输出、子 agent 报告）会被截断到 MAX_FIELD_CHARS，避免单帧过大。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MAX_FIELD_CHARS = 4000

# 事件类型常量，避免各处手写字符串写错
RUN_START = "run_start"
TOKEN = "token"
TOOL_START = "tool_start"
TOOL_END = "tool_end"
SUBAGENT_START = "subagent_start"
SUBAGENT_END = "subagent_end"
TODO = "todo"
MESSAGE = "message"
ERROR = "error"
RUN_END = "run_end"


def truncate(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """把可能很大的字段裁剪成可安全放进单帧 SSE 的形式。"""
    if value is None:
        return None
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            value = str(value)
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n…（已截断，原始长度 {len(value)} 字符）"


@dataclass
class SSEEvent:
    """一个待下发的 SSE 帧。"""

    event: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str | None = None

    def to_sse_dict(self) -> dict[str, Any]:
        """转成 sse-starlette 认识的 dict 形式。"""
        frame: dict[str, Any] = {
            "event": self.event,
            "data": json.dumps(self.data, ensure_ascii=False, default=str),
        }
        if self.id:
            frame["id"] = self.id
        return frame
