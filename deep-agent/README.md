# Deep Agent Starter

基于 **deepagents**（LangChain 官方 Deep Agents，构建在 LangGraph 之上）的主 agent + 子 agent 项目骨架，
后端通过 **SSE** 把 agent 的执行过程实时推给前端。

主 agent 不亲自干活，它负责**规划 → 分派 → 汇总**；具体任务交给隔离上下文的子 agent 执行，
这样既能并行、又能避免单个子任务的冗长中间过程污染主上下文。

## 架构

```
                    ┌──────────────────────────────────────────────┐
   浏览器 / 前端 ──► │  FastAPI                                     │
   (EventSource)    │                                              │
        ▲           │  GET/POST /api/chat/stream  ──► SSE 事件流    │
        │           │                                              │
        │           │  ┌─────────────── app/streaming ───────────┐ │
        └───────────┼──│ adapter: astream_events → 归一化事件     │ │
    结构化 SSE 事件  │  └───────────────────┬─────────────────────┘ │
                    │                      │                       │
                    │  ┌───────────────────▼─────────────────────┐ │
                    │  │  主 agent (create_deep_agent)           │ │
                    │  │  · write_todos  规划                    │ │
                    │  │  · task         派发子 agent            │ │
                    │  │  · 虚拟文件系统  存放中间产物            │ │
                    │  └──────┬─────────────┬─────────────┬──────┘ │
                    │         │             │             │        │
                    │    ┌────▼───┐   ┌─────▼───┐   ┌─────▼────┐   │
                    │    │researcher│ │  coder  │   │ reviewer │   │
                    │    └────────┘   └─────────┘   └──────────┘   │
                    └──────────────────────────────────────────────┘
                             每个子 agent 独立上下文、独立工具集
```

一次请求的事件流：

```
run_start → token… → todo → tool_start/tool_end… → subagent_start → (子 agent 内部 token/工具) → subagent_end → token… → run_end
```

## 目录结构

```
deep-agent/
├── app/
│   ├── main.py                  FastAPI 入口、lifespan、CORS、静态页挂载
│   ├── config.py                全部配置（.env 驱动）
│   ├── llm.py                   多 provider 模型工厂  ← 换模型只改 .env
│   ├── api/routes.py            HTTP 接口
│   ├── agents/
│   │   ├── main_agent.py        主 agent 组装 + 版本兼容适配
│   │   ├── registry.py          子 agent 注册表（SubAgentSpec）
│   │   └── subagents/           researcher / coder / reviewer
│   ├── tools/builtin.py         自定义工具（calculator 等）
│   └── streaming/
│       ├── events.py            SSE 事件契约  ← 前后端的接口约定
│       └── adapter.py           astream_events → SSE 事件  ← 唯一与框架耦合处
├── static/index.html            零依赖调试前端
├── scripts/diagnose.py          模型接入诊断（base_url / 鉴权 / 格式 / 模型名）
├── run.py                       本地启动脚本
├── requirements.txt
└── .env.example
```

## 快速开始

```bash
cd deep-agent

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，至少填一个 provider 的 key

python run.py          # 或 uvicorn app.main:app --reload --port 8000
```

打开 <http://localhost:8000> 就是调试台：能看到 token 实时输出、工具调用折叠面板、
子 agent 的嵌套调用块，以及主 agent 的待办清单。

## 模型接入

改 `.env` 即可切换，代码不用动。三种方式：

```bash
# 1) OpenAI
MODEL_PROVIDER=openai
MODEL_NAME=gpt-4o-mini
OPENAI_API_KEY=sk-xxx

# 2) OpenAI 兼容端点（DeepSeek / 通义 / vLLM / Ollama…）
MODEL_PROVIDER=openai_compatible
MODEL_NAME=deepseek-chat
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.deepseek.com/v1

# 3) Anthropic
MODEL_PROVIDER=anthropic
MODEL_NAME=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-xxx
```

还可以让主 agent 和子 agent 用不同厂商的模型来控制成本（格式 `provider:model`）：

```bash
MAIN_MODEL=anthropic:claude-sonnet-4-6
SUBAGENT_MODEL=openai_compatible:deepseek-chat
```

## HTTP / SSE 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查，返回当前 provider/model 和子 agent 列表 |
| GET | `/api/agents` | 列出可调度的子 agent |
| GET | `/api/chat/stream?message=&thread_id=` | **SSE**，给浏览器原生 `EventSource` |
| POST | `/api/chat/stream` | **SSE**，JSON body `{message, thread_id}`，正式前端推荐 |
| POST | `/api/chat` | 非流式，方便脚本冒烟测试 |
| DELETE | `/api/threads/{thread_id}` | 清空某会话历史 |

多轮上下文按 `thread_id` 隔离，由 checkpointer 维护；不传 `thread_id` 会自动新建。

### SSE 事件契约

前端只需要认这几种事件，后端换框架不影响前端：

| event | data |
| --- | --- |
| `run_start` | `{run_id, thread_id, started_at}` |
| `token` | `{text, agent}` — `agent` 为 `main` 或子 agent 名 |
| `tool_start` | `{id, name, args, agent}` |
| `tool_end` | `{id, name, output, ok, agent}` |
| `subagent_start` | `{id, name, description, input}` |
| `subagent_end` | `{id, name, output, ok}` |
| `todo` | `{todos}` — 主 agent 更新待办清单 |
| `message` | `{agent, content}` — 某条完整回复 |
| `error` | `{message, recoverable}` |
| `run_end` | `{run_id, elapsed_ms, ok}` |

约定：每个 run 一定以 `run_start` 开始、`run_end` 结束；大字段会截断到 4000 字符
（`app/streaming/events.py` 的 `MAX_FIELD_CHARS`）。

用 curl 验证：

```bash
curl -N "http://localhost:8000/api/chat/stream?message=你好"
```

## 如何新增一个子 agent

只改两个地方。

**1. 新建 `app/agents/subagents/writer.py`：**

```python
from ..registry import SubAgentSpec
from ...tools import search_knowledge_base

SUBAGENT = SubAgentSpec(
    name="writer",
    description="文案撰写专员。适合把已有结论组织成对外可发布的成稿。",
    prompt="你是一名文案…（这个子 agent 自己的 system prompt）",
    tools=[search_knowledge_base],
    metadata={"display_name": "文案", "icon": "pen"},
)
```

**2. 在 `app/agents/registry.py` 的 `load_default_subagents()` 里注册：**

```python
from .subagents import coder, researcher, reviewer, writer
for module in (researcher, coder, reviewer, writer):
    ...
```

`description` 是最关键的一个字段——主 agent 完全靠它判断该不该把任务派给这个子 agent，
所以要写「擅长什么、什么场景用它」，而不是写它的内部实现。

子 agent 默认继承主 agent 的全部工具和模型；在 `SubAgentSpec` 里传 `tools=[...]` 可以收窄工具集，
传 `model_role="subagent"` 可以让它使用 `SUBAGENT_MODEL` 指定的模型。

## 如何新增一个工具

在 `app/tools/builtin.py` 里用 `@tool` 装饰一个函数，加进 `ALL_TOOLS`。
docstring 会被 LLM 当成工具说明，必须写清楚用途和参数。

```python
@tool
def query_order(order_id: str) -> str:
    """根据订单号查询订单状态。"""
    ...
```

## 部署注意

- **Nginx 反代必须关缓冲**，否则 SSE 会被攒成一坨才吐出。代码里已经带了
  `X-Accel-Buffering: no`，Nginx 侧再加 `proxy_buffering off;` 双保险。
- **多轮记忆**默认用 `InMemorySaver`，进程重启即丢。生产换成
  `langgraph.checkpoint.sqlite.SqliteSaver` 或 `PostgresSaver`，在 `app/main.py`
  的 lifespan 里替换即可。
- **CORS**：`.env` 里 `CORS_ORIGINS` 默认 `*`，上线前改成具体域名。
- **长任务**：`RECURSION_LIMIT` 控制子 agent 互相调用的上限，防止跑飞。

## 常见问题

### 报 `OpenAIModelNotFoundError: 404 page not found`

这是 `base_url` 层级填错了。两种 SDK 的约定**不一样**，非常容易踩：

| provider | base_url 是否含 `/v1` | SDK 实际请求的路径 |
| --- | --- | --- |
| OpenAI / 兼容端点 | **要**含 | `{base_url}/chat/completions` |
| Anthropic | **不要**含 | `{base_url}/v1/messages` |

所以同一个网关，两种 provider 要填的 base_url 是**不同的**。多填或少填一层 `/v1`，
表现就是 `404 page not found`（Go 路由的默认 404 响应体，纯文本）。

拿不准就先跑诊断脚本，它会把每个候选路径都试一遍，直接告诉你 `.env` 该怎么写：

```bash
python scripts/diagnose.py
```

### 网关只认 Anthropic 格式

有些企业网关（尤其是只服务 Claude Code 这类客户端的那种）只实现了 Anthropic Messages API，
`POST /chat/completions` 一律返回 404。这种情况下要把 `MODEL_PROVIDER` 设成 `anthropic`，
key 填到 `ANTHROPIC_API_KEY`（而不是 OpenAI 那一组），`ANTHROPIC_BASE_URL` 填到 `/v1` 之前。
诊断脚本会自动识别并给出完整配置。

### 改完 `.env` 没生效

`get_settings()` 带了 `lru_cache`，而且 `.env` 不在 uvicorn 的 `reload_dirs`（只监听 `app/`）里，
热重载不会重新读配置。**必须手动 Ctrl+C 重启**。

## 接下来可以做的

- 把 `InMemorySaver` 换成持久化 checkpointer，会话可恢复
- 给 `/api/chat/stream` 加鉴权（SSE 场景下注意 EventSource 不能自定义 header，
  通常用 cookie 或一次性 token 走 query）
- 用 deepagents 的 `interrupt_on` 给敏感工具加人工确认
- 接真实检索：把 `search_knowledge_base` 换成你的向量库 / ES
- 前端换成 React，事件契约不用变
