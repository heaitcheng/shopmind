import pytest

from app.core.llm import _check_api_key, _http_clients


def test_空密钥报清晰错误():
    with pytest.raises(RuntimeError, match="未配置 LLM_API_KEY"):
        _check_api_key("")


def test_中文占位符报清晰错误():
    with pytest.raises(RuntimeError, match="非 ASCII"):
        _check_api_key("在这里粘贴你的智谱APIKey")


def test_英文占位符报清晰错误():
    with pytest.raises(RuntimeError, match="占位符"):
        _check_api_key("sk-your-api-key")


def test_正常密钥放行():
    _check_api_key("abc123def456.ghi789")


def test_默认不读环境代理(monkeypatch):
    """服务进程会继承 shell 的 http_proxy，端口一变就全是 Connection error。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")

    sync_client, async_client = _http_clients("")

    assert sync_client.trust_env is False
    assert async_client.trust_env is False


def test_显式配了代理才走代理(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")

    bare, bare_async = _http_clients("")
    proxied, proxied_async = _http_clients("http://127.0.0.1:7890")

    assert bare.trust_env is False and proxied.trust_env is False
    # httpx 把代理挂在 mounts 上；不配代理时 mounts 为空
    assert len(bare._mounts) == 0
    assert len(proxied._mounts) == 1
    assert len(bare_async._mounts) == 0
    assert len(proxied_async._mounts) == 1
