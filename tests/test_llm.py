import pytest

from app.llm import _check_api_key


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
