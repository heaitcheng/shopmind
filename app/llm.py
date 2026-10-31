import httpx
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


def _http_clients(proxy: str) -> tuple[httpx.Client, httpx.AsyncClient]:
    """构造不读环境代理的 http 客户端。

    默认 trust_env=False 是有意的：服务进程会继承启动时 shell 的 http_proxy，
    而这类代理端口可能随时变化。继承到过期端口时，上游请求会全部失败并报
    "Connection error."，看起来像上游挂了，极难定位。
    需要走代理时在 .env 里显式写 LLM_PROXY。
    """
    kwargs = {"trust_env": False}
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs), httpx.AsyncClient(**kwargs)


@lru_cache(maxsize=8)
def _build_llm(
    base_url: str,
    model: str,
    api_key: str,
    temperature: float,
    timeout: float,
    thinking: str,
    max_retries: int,
    proxy: str,
) -> ChatOpenAI:
    """按配置组合缓存实例：同配置复用连接池，配置变了自动重建。"""
    kwargs: dict = {}
    # 智谱专用开关：不传则上游用默认值；显式 disabled 见 docs/ch01-spec.md 4.7
    if thinking:
        kwargs["extra_body"] = {"thinking": {"type": thinking}}

    sync_client, async_client = _http_clients(proxy)

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
        http_client=sync_client,
        http_async_client=async_client,
        **kwargs,
    )


def get_llm() -> ChatOpenAI:
    """统一按 OpenAI 协议构造上游客户端，换供应商只改 .env。

    配置不缓存，所以改完 .env 立刻生效；只有「完全相同的配置」才复用实例。
    """
    s = get_settings()
    _check_api_key(s.llm_api_key)
    return _build_llm(
        s.llm_base_url,
        s.llm_model,
        s.llm_api_key,
        s.llm_temperature,
        s.llm_timeout,
        s.llm_thinking,
        s.llm_max_retries,
        s.llm_proxy,
    )
