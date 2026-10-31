"""工具注册表与执行器的验收测试。

全部使用假工具：不连数据库、不发网络请求。
"""

import asyncio
import json

import pytest
from langchain_core.tools import tool

from app.tools.registry import ToolRegistry, run_tool


@tool
def echo_tool(text: str) -> str:
    """原样回显传入的文本。"""
    return f"echo:{text}"


def test_register_duplicate_name_raises():
    registry = ToolRegistry()
    registry.register(echo_tool)
    with pytest.raises(ValueError):
        registry.register(echo_tool)


def test_get_unknown_name_raises_keyerror():
    with pytest.raises(KeyError):
        ToolRegistry().get("not_registered")


def test_all_returns_registered_tools():
    registry = ToolRegistry()
    registry.register(echo_tool)
    assert [t.name for t in registry.all()] == ["echo_tool"]


async def test_invalid_args_returns_error_and_never_calls_tool():
    calls: list[int] = []

    @tool
    def counted(value: int) -> str:
        """记录被调用的次数。"""
        calls.append(value)
        return "ok"

    result = await run_tool(counted, {}, timeout=1.0, max_retries=1)

    assert result.ok is False
    assert result.error.startswith("参数不合法")
    assert calls == []  # 参数校验失败时绝不执行工具函数


async def test_timeout_then_success_retries():
    state = {"attempts": 0}

    @tool
    async def flaky(attempt: int) -> str:
        """第一次超时，第二次成功。"""
        state["attempts"] += 1
        if state["attempts"] == 1:
            await asyncio.sleep(0.5)
        return "第二次成功"

    result = await run_tool(flaky, {"attempt": 1}, timeout=0.05, max_retries=1)

    assert result.ok is True
    assert result.data == "第二次成功"  # str 返回值原样保留，不二次编码
    assert state["attempts"] == 2


async def test_retries_exhausted_by_timeout():
    state = {"attempts": 0}

    @tool
    async def always_slow(x: int) -> str:
        """每次都会超时。"""
        state["attempts"] += 1
        await asyncio.sleep(0.5)
        return "不会到达"

    result = await run_tool(always_slow, {"x": 1}, timeout=0.05, max_retries=1)

    assert result.ok is False
    assert "超时" in result.error
    assert state["attempts"] == 2  # 总共尝试 1 + max_retries 次


async def test_tool_exception_is_wrapped_not_raised():
    @tool
    def boom(x: int) -> str:
        """总是抛错。"""
        raise RuntimeError("数据库炸了")

    result = await run_tool(boom, {"x": 1}, timeout=1.0, max_retries=1)

    assert result.ok is False
    assert "数据库炸了" in result.error


async def test_success_returns_json_and_elapsed_ms():
    @tool
    def add(a: int, b: int) -> dict:
        """计算两个整数之和。"""
        return {"sum": a + b}

    result = await run_tool(add, {"a": 1, "b": 2}, timeout=1.0, max_retries=0)

    assert result.ok is True
    assert json.loads(result.data) == {"sum": 3}
    assert result.elapsed_ms >= 0
