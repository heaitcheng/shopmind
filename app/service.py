import uuid
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.config import Settings
from app.memory import SessionStore, build_context
from app.prompts import render_extract_instruction, render_system
from app.schemas import AfterSaleRequest


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
    ) -> None:
        self.model = model
        self.store = store
        self.settings = settings
        self._new_id = session_id_factory or (lambda: uuid.uuid4().hex)

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
        async for chunk in self.model.astream(messages):
            text = chunk.content
            if isinstance(text, str) and text:
                parts.append(text)
                yield {"event": "token", "data": {"delta": text}}

        answer = "".join(parts)
        self.store.append(sid, [HumanMessage(user_input), AIMessage(answer)])
        yield {
            "event": "done",
            "data": {"content": answer, "session_id": sid, "trimmed": trimmed},
        }

    async def extract(self, text: str) -> AfterSaleRequest:
        structured = self.model.with_structured_output(
            AfterSaleRequest, method=self.settings.structured_method
        )
        return await structured.ainvoke(
            [SystemMessage(render_extract_instruction()), HumanMessage(text)]
        )
