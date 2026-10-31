"""工具注册表与执行器。

执行器把「参数校验 → 执行 → 超时重试 → 异常封装」收敛到一处，
永远返回 ToolResult，绝不向上抛异常。
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    data: str | None = None  # 成功时是 json 字符串
    error: str | None = None  # 失败时是可读中文错误
    elapsed_ms: int = 0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, tool: Any) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具已注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Any:
        return self._tools[name]

    def all(self) -> list[Any]:
        return list(self._tools.values())


def _validation_brief(exc: Exception) -> str:
    """把 pydantic 的长报错压成一行，方便直接给用户看。"""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        parts = [
            f"{'.'.join(map(str, e.get('loc', ())))}: {e.get('msg', '')}".strip(": ")
            for e in errors()
        ]
        if parts:
            return "; ".join(parts)
    return str(exc)


async def run_tool(
    tool: Any, args: dict, timeout: float, max_retries: int
) -> ToolResult:
    start = time.perf_counter()

    def _result(ok: bool, data: str | None = None, error: str | None = None) -> ToolResult:
        return ToolResult(
            ok=ok,
            data=data,
            error=error,
            elapsed_ms=round((time.perf_counter() - start) * 1000),
        )

    # 第一关：参数校验。失败时绝不执行工具函数。
    try:
        validated = tool.args_schema.model_validate(args)
    except Exception as exc:  # noqa: BLE001 - 校验失败一律归为参数问题
        return _result(False, error=f"参数不合法: {_validation_brief(exc)}")

    # 第二关：执行 + 超时重试，总共尝试 1 + max_retries 次。
    attempts = 1 + max(0, max_retries)
    for attempt in range(attempts):
        try:
            raw = await asyncio.wait_for(tool.ainvoke(validated), timeout=timeout)
        except asyncio.TimeoutError:
            if attempt == attempts - 1:
                return _result(False, error="执行超时")
            continue
        except Exception as exc:  # noqa: BLE001 - 业务异常不重试，原样封装
            return _result(False, error=str(exc))

        # 第四关：成功。str 原样返回，其余转 json。
        if isinstance(raw, str):
            return _result(True, data=raw)
        try:
            return _result(True, data=json.dumps(raw, ensure_ascii=False, default=str))
        except Exception as exc:  # noqa: BLE001 - 序列化失败也不许抛
            return _result(False, error=str(exc))
