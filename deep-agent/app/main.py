"""FastAPI 应用入口。

启动：
    uvicorn app.main:app --reload --port 8000
或：
    python run.py
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .agents import build_agent, load_default_subagents
from .api import router as api_router
from .config import get_settings
from .llm import ModelConfigError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
)
logger = logging.getLogger("deep-agent")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings

    registry = load_default_subagents()
    app.state.subagent_specs = [spec.to_public_dict() for spec in registry.all()]
    app.state.subagent_names = registry.names()

    # 用内存 checkpointer 维护多轮上下文（生产可换成 SqliteSaver / PostgresSaver）
    checkpointer = None
    try:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
    except Exception as exc:  # pragma: no cover - 依赖缺失时降级为无记忆
        logger.warning("未能初始化 checkpointer，本次运行将不具备多轮记忆: %s", exc)

    # 模型没配好时不阻断启动：服务照常起来，接口返回可读的错误，
    # 这样打开调试页就能看到「该配哪个环境变量」，而不是连不上服务。
    try:
        app.state.agent = build_agent(settings, registry, checkpointer=checkpointer)
        app.state.agent_error = None
        logger.info("主 agent 初始化完成，子 agent: %s", app.state.subagent_names)
    except ModelConfigError as exc:
        app.state.agent = None
        app.state.agent_error = str(exc)
        logger.error("模型未配置，服务以降级模式启动：%s", exc)
    except Exception as exc:  # noqa: BLE001
        app.state.agent = None
        app.state.agent_error = f"{type(exc).__name__}: {exc}"
        logger.exception("主 agent 初始化失败")

    yield

    logger.info("服务关闭")


app = FastAPI(
    title="Deep Agent Starter",
    description="基于 deepagents 的主 agent + 子 agent 骨架，SSE 流式对接前端。",
    version="0.1.0",
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=False,  # 与 allow_origins=["*"] 不能同时为 True
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def block_when_agent_unavailable(request, call_next):
    """模型没配好时，业务接口直接给出可读错误，而不是 500 堆栈。"""
    path = request.url.path
    if (
        path.startswith("/api/")
        and path not in ("/api/health", "/api/agents")
        and getattr(request.app.state, "agent", None) is None
    ):
        return JSONResponse(
            status_code=503,
            content={
                "error": "agent_unavailable",
                "message": getattr(request.app.state, "agent_error", "主 agent 未初始化"),
                "hint": "请复制 .env.example 为 .env 并填写模型配置后重启服务。",
            },
        )
    return await call_next(request)


app.include_router(api_router)

# 调试页挂在根路径，注意要在 api 路由之后注册
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:  # pragma: no cover
    logger.warning("未找到静态目录 %s，跳过调试页挂载", STATIC_DIR)
