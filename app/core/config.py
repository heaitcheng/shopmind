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
    # 上游 429/5xx 时的自动重试次数，由 openai SDK 做指数退避
    llm_max_retries: int = 2
    # 显式代理。留空则忽略环境里的 http_proxy/https_proxy（默认行为，更可预测）
    llm_proxy: str = ""
    # 智谱专用。留空则不发送 thinking 参数；必须为 disabled，原因见 docs/ch01-spec.md 4.7
    llm_thinking: str = ""

    # 上下文预算
    history_max_tokens: int = 1500

    # 结构化输出方式：function_calling / json_schema / json_mode
    structured_method: str = "function_calling"

    shop_name: str = "小店"

    # 数据层。空字符串默认，避免没配 .env 时导入即崩
    database_url: str = ""
    # 测试专用库。测试夹具会清表，必须和演示库分开，否则跑一次 pytest 演示数据就没了
    test_database_url: str = ""
    tool_timeout: float = 5.0
    tool_max_retries: int = 1


def get_settings() -> Settings:
    """故意不缓存：改完 .env 下一次请求就生效，不用重启服务。"""
    return Settings()
