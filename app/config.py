from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全部运行期配置从 .env 读，代码里不出现任何密钥常量。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 上游模型：统一 OpenAI 协议
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4.7-flash"
    llm_api_key: str = ""
    llm_temperature: float = 0.7
    llm_timeout: float = 60.0
    # 智谱专用。留空则不发送 thinking 参数；必须为 disabled，原因见 docs/ch01-spec.md 4.7
    llm_thinking: str = ""

    # 上下文预算
    history_max_tokens: int = 1500

    # 结构化输出方式：function_calling / json_schema / json_mode
    structured_method: str = "function_calling"

    shop_name: str = "小店"


@lru_cache
def get_settings() -> Settings:
    return Settings()
