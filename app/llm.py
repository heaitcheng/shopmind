from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


def _check_api_key(key: str) -> None:
    """密钥问题要在构造阶段就说人话，不然后面会变成 Authorization 头的 ascii 编码错误。"""
    if not key or not key.strip():
        raise RuntimeError("未配置 LLM_API_KEY：请复制 .env.example 为 .env 并填入真实密钥")
    if not key.isascii():
        raise RuntimeError(
            "LLM_API_KEY 含非 ASCII 字符，看起来还是占位符。请填真实密钥"
        )
    lowered = key.lower()
    if "your" in lowered or "xxx" in lowered or "placeholder" in lowered:
        raise RuntimeError("LLM_API_KEY 仍是占位符，请填真实密钥")


@lru_cache
def get_llm() -> ChatOpenAI:
    """统一按 OpenAI 协议构造上游客户端，换供应商只改 .env。"""
    s = get_settings()

    _check_api_key(s.llm_api_key)

    kwargs: dict = {}
    # 智谱专用开关：不传则上游用默认值；显式 disabled 见 docs/ch01-spec.md 4.7
    if s.llm_thinking:
        kwargs["extra_body"] = {"thinking": {"type": s.llm_thinking}}

    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        temperature=s.llm_temperature,
        timeout=s.llm_timeout,
        **kwargs,
    )
