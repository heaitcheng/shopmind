import uuid
from collections.abc import AsyncIterator

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import Settings
from app.core.prompts import render_extract_instruction, render_system
from app.memory import SessionStore, build_context
from app.schemas import AfterSaleRequest
from app.tools.registry import ToolResult, run_tool


_NULLISH = {"", "null", "none", "nil", "n/a", "na", "undefined", "-"}


def _clean_text(value: str | None) -> str | None:
    """模型经常把空值写成字符串 "null"，这里统一归一成 None。"""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    return None if stripped.lower() in _NULLISH else stripped


class ChatService:
    """把「取历史 → 裁剪 → 拼消息 → 调模型 → 产出事件」串起来。

    model 通过构造注入，测试里换成 FakeModel 即可完全不碰网络。
    """

    def __init__(
        self,
        model,
        store: SessionStore,
        settings: Settings,
        session_id_factory=None,
        registry=None,
    ) -> None:
        self.model = model
        self.store = store
        self.settings = settings
        self._new_id = session_id_factory or (lambda: uuid.uuid4().hex)
        self.registry = registry

    def _build_messages(
        self, history: list[BaseMessage], user_input: str
    ) -> tuple[list[BaseMessage], int]:
        kept, trimmed = build_context(history, self.settings.history_max_tokens)
        messages: list[BaseMessage] = [
            SystemMessage(render_system(self.settings.shop_name)),
            *kept,
            HumanMessage(user_input),
        ]
        return messages, trimmed

    async def stream(
        self, session_id: str | None, user_input: str
    ) -> AsyncIterator[dict]:
        """产出 token / done 事件。历史只在整轮成功后落盘。"""
        sid = session_id or self._new_id()
        messages, trimmed = self._build_messages(self.store.get(sid), user_input)

        parts: list[str] = []
        # 有 assistant 历史时，GLM 会在回答前吐一个换行当段落分隔。
        # 在推送前把它吃掉，否则前端 pre-wrap 会渲染出一行空白。
        pending_leading = True

        async for chunk in self.model.astream(messages):
            text = chunk.content
            if not isinstance(text, str) or not text:
                continue
            if pending_leading:
                text = text.lstrip()
                if not text:  # 整块都是空白，继续等正文
                    continue
                pending_leading = False
            parts.append(text)
            yield {"event": "token", "data": {"delta": text}}

        answer = "".join(parts)
        self.store.append(sid, [HumanMessage(user_input), AIMessage(answer)])
        yield {
            "event": "done",
            "data": {"content": answer, "session_id": sid, "trimmed": trimmed},
        }

    async def stream_with_tools(
        self, session_id: str | None, user_input: str
    ) -> AsyncIterator[dict]:
        """单轮工具编排：第一趟让模型决策并执行工具，第二趟只负责组织回答。

        第二趟刻意不 bind_tools：模型没有工具可调，从机制上保证只调一轮。
        """
        if self.registry is None:
            # 没有注册表就退化成纯文本流，与 stream() 行为一致
            async for event in self.stream(session_id, user_input):
                if event["event"] == "done":
                    event["data"]["tools"] = []
                yield event
            return

        sid = session_id or self._new_id()
        messages, trimmed = self._build_messages(self.store.get(sid), user_input)
        tool_trace: list[dict] = []
        first_parts: list[str] = []
        second_parts: list[str] = []

        # 第一趟：带工具。分片累积，同时把正文立刻推给前端。
        bound = self.model.bind_tools(self.registry.all())
        gathered = None
        pending_leading = True

        async for chunk in bound.astream(messages):
            gathered = chunk if gathered is None else gathered + chunk
            text = chunk.content
            if not isinstance(text, str) or not text:
                continue
            if pending_leading:
                text = text.lstrip()
                if not text:  # 整块都是空白，继续等正文
                    continue
                pending_leading = False
            first_parts.append(text)
            yield {"event": "token", "data": {"delta": text}}

        # 累积后的 chunk 已经把 args 还原成 dict，无需自己解析 JSON
        tool_calls: list[dict] = list(gathered.tool_calls) if gathered is not None else []

        if tool_calls:
            executed: list[tuple[dict, ToolResult]] = []
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("args") or {}
                yield {
                    "event": "tool",
                    "data": {"name": name, "args": args, "status": "running"},
                }

                try:
                    tool = self.registry.get(name)
                except KeyError:  # 模型幻觉了一个不存在的工具名，不能中断整轮
                    result = ToolResult(ok=False, error=f"未知工具: {name}")
                else:
                    result = await run_tool(
                        tool,
                        args,
                        timeout=self.settings.tool_timeout,
                        max_retries=self.settings.tool_max_retries,
                    )

                yield {
                    "event": "tool",
                    "data": {
                        "name": name,
                        "args": args,
                        "status": "ok" if result.ok else "error",
                        "elapsed_ms": result.elapsed_ms,
                        "error": result.error,
                    },
                }
                tool_trace.append(
                    {
                        "id": tc.get("id"),
                        "name": name,
                        "args": args,
                        "ok": result.ok,
                        "elapsed_ms": result.elapsed_ms,
                        "error": result.error,
                        # 原始结果随 done 帧交给接口层落库；前端渲染徽章时忽略即可
                        "result": result.data if result.ok else None,
                    }
                )
                executed.append((tc, result))

            messages.append(
                AIMessage(content="".join(first_parts), tool_calls=tool_calls)
            )
            for tc, result in executed:
                messages.append(
                    ToolMessage(
                        content=result.data if result.ok else result.error,
                        tool_call_id=tc["id"],
                    )
                )

            if any(not result.ok for _, result in executed):
                messages.append(
                    SystemMessage(
                        content="上面有一条工具调用失败了。只能如实说明这次查询没成功、"
                        "建议用户转人工，绝对不许编造查询结果，也不许假装查到了。"
                    )
                )

            # 第二趟：不带工具，模型没法再调一次
            pending_leading = True
            async for chunk in self.model.astream(messages):
                text = chunk.content
                if not isinstance(text, str) or not text:
                    continue
                if pending_leading:
                    text = text.lstrip()
                    if not text:
                        continue
                    pending_leading = False
                second_parts.append(text)
                yield {"event": "token", "data": {"delta": text}}

        answer = "".join(first_parts) + "".join(second_parts)
        # 中间那条 AIMessage(tool_calls) 与 ToolMessage 不落盘：OpenAI 协议要求它们成对出现，
        # 只存一半会让下一轮 400；全存又会让上下文膨胀，而 answer 里已有工具结论。
        self.store.append(sid, [HumanMessage(user_input), AIMessage(answer)])
        yield {
            "event": "done",
            "data": {
                "content": answer,
                "session_id": sid,
                "trimmed": trimmed,
                "tools": tool_trace,
            },
        }

    async def extract(self, text: str) -> AfterSaleRequest:
        structured = self.model.with_structured_output(
            AfterSaleRequest, method=self.settings.structured_method
        )
        raw = await structured.ainvoke(
            [SystemMessage(render_extract_instruction()), HumanMessage(text)]
        )
        return raw.model_copy(
            update={
                "order_id": _clean_text(raw.order_id),
                "reason": _clean_text(raw.reason),
                "expected_solution": _clean_text(raw.expected_solution),
            }
        )
