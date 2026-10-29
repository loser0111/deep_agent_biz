"""全局配置。

所有配置项都可以通过环境变量或 .env 文件覆盖，环境变量优先级更高。
字段名小写即可，pydantic-settings 会自动做大小写不敏感的映射，
例如 `model_provider` 对应环境变量 `MODEL_PROVIDER`。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 允许 model_* 开头的字段名（pydantic v2 默认会把它当作保留命名空间）
        protected_namespaces=(),
    )

    # ---------------------------------------------------------------- 模型接入
    # openai | openai_compatible | anthropic
    model_provider: str = "openai"

    # 默认模型名。走 openai_compatible 时填目标服务商的模型名，
    # 例如 deepseek-chat / qwen-max / 本地 vLLM 暴露的模型名。
    model_name: str = "gpt-4o-mini"

    # 角色级覆盖，格式为 "provider:model" 或只写 "model"。
    # 例如 MAIN_MODEL=anthropic:claude-sonnet-4-6
    # 留空则全部使用 model_provider + model_name。
    main_model: str | None = None
    subagent_model: str | None = None

    # OpenAI / OpenAI 兼容端点（DeepSeek、通义、vLLM、Ollama...）
    openai_api_key: str | None = None
    openai_base_url: str | None = None

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None

    temperature: float = 0.0
    max_tokens: int | None = None

    # ---------------------------------------------------------------- 服务
    host: str = "0.0.0.0"
    port: int = 8000
    # 逗号分隔，* 表示放开全部（仅建议本地调试使用）
    cors_origins: str = "*"

    # ---------------------------------------------------------------- Agent
    # deep agent 的虚拟文件系统根目录（后端为 filesystem 时生效）
    workspace_dir: str = "./workspace"
    # 单次运行的图递归上限，防止子 agent 无限互相调用
    recursion_limit: int = 60
    # 同时保留多少轮对话（由 checkpointer 按 thread_id 维护）
    max_history_messages: int = 40

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
