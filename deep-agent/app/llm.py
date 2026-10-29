"""多 provider 模型工厂。

骨架里把「用哪家模型」收敛到一个函数 `build_chat_model(role)`，
上层（主 agent / 子 agent）只关心角色，不关心具体厂商。

切换方式（改 .env 即可，无需动代码）：

    # 1) OpenAI
    MODEL_PROVIDER=openai
    MODEL_NAME=gpt-4o-mini
    OPENAI_API_KEY=sk-xxx

    # 2) OpenAI 兼容端点（DeepSeek / 通义 / vLLM / Ollama ...）
    MODEL_PROVIDER=openai_compatible
    MODEL_NAME=deepseek-chat
    OPENAI_API_KEY=sk-xxx
    OPENAI_BASE_URL=https://api.deepseek.com/v1

    # 3) Anthropic
    MODEL_PROVIDER=anthropic
    MODEL_NAME=claude-sonnet-4-6
    ANTHROPIC_API_KEY=sk-ant-xxx

    # 4) 主/子 agent 用不同厂商
    MAIN_MODEL=anthropic:claude-sonnet-4-6
    SUBAGENT_MODEL=openai_compatible:deepseek-chat
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from .config import Settings, get_settings

# provider 别名 -> 归一化后的名字
_PROVIDER_ALIASES = {
    "openai": "openai",
    "openai_compatible": "openai",
    "compatible": "openai",
    "deepseek": "openai",
    "qwen": "openai",
    "dashscope": "openai",
    "vllm": "openai",
    "ollama": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
}

# Anthropic 的 messages API 必须显式给出 max_tokens
_ANTHROPIC_DEFAULT_MAX_TOKENS = 4096


class ModelConfigError(RuntimeError):
    """模型配置缺失或非法时抛出，便于在启动阶段快速失败。"""


def _require(value: str | None, env_name: str) -> str:
    if not value:
        raise ModelConfigError(
            f"缺少环境变量 {env_name}。请复制 .env.example 为 .env 并填写，"
            f"参考 README 的「模型接入」章节。"
        )
    return value


def resolve_model_spec(role: str, settings: Settings) -> tuple[str, str]:
    """决定某个角色最终使用 (provider, model_name)。

    role 为 "main" 时读取 MAIN_MODEL，其余（子 agent）读取 SUBAGENT_MODEL，
    两者都支持 "provider:model" 简写。
    """
    provider = (settings.model_provider or "openai").strip().lower()
    model_name = (settings.model_name or "").strip()

    override = settings.main_model if role == "main" else settings.subagent_model
    if override:
        override = override.strip()
        if ":" in override:
            provider, model_name = override.split(":", 1)
            provider, model_name = provider.strip().lower(), model_name.strip()
        else:
            model_name = override

    if not model_name:
        raise ModelConfigError("模型名为空，请检查 MODEL_NAME / MAIN_MODEL / SUBAGENT_MODEL 配置。")

    normalized = _PROVIDER_ALIASES.get(provider)
    if normalized is None:
        raise ModelConfigError(
            f"未知的 MODEL_PROVIDER={provider!r}，可选："
            f"{', '.join(sorted(set(_PROVIDER_ALIASES)))}"
        )
    return normalized, model_name


def build_chat_model(role: str = "main", settings: Settings | None = None) -> BaseChatModel:
    """按角色构建一个 LangChain ChatModel。

    子 agent 不传 model 时会继承主 agent 的模型；这里显式构建是为了让
    「主 agent 用强模型、子 agent 用便宜模型」这类成本策略只改 .env 就能生效。
    """
    settings = settings or get_settings()
    provider, model_name = resolve_model_spec(role, settings)

    common: dict[str, Any] = {"temperature": settings.temperature}

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if settings.max_tokens:
            common["max_tokens"] = settings.max_tokens
        return ChatOpenAI(
            model=model_name,
            api_key=_require(settings.openai_api_key, "OPENAI_API_KEY"),
            base_url=settings.openai_base_url or None,
            **common,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            api_key=_require(settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
            base_url=settings.anthropic_base_url or None,
            max_tokens=settings.max_tokens or _ANTHROPIC_DEFAULT_MAX_TOKENS,
            **common,
        )

    # 理论上不可达，resolve_model_spec 已经做过校验
    raise ModelConfigError(f"provider {provider!r} 暂未支持")
