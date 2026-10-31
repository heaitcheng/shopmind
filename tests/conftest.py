"""测试共用夹具：FakeModel 替代真实上游，不发任何网络请求。"""

import pytest
from langchain_core.messages import AIMessageChunk


class FakeModel:
    """满足 ChatService 所需的最小接口：astream + with_structured_output。"""

    def __init__(self, reply: str = "好的，我来帮您处理。"):
        self.reply = reply
        self.calls: list[list] = []              # 每次 astream 收到的消息
        self.structured_calls: list[tuple] = []  # (schema, method)
        self.structured_result = None
        self.last_extract_messages: list = []
        self.raise_on_stream: Exception | None = None

    async def astream(self, messages, **kwargs):
        self.calls.append(list(messages))
        if self.raise_on_stream:
            raise self.raise_on_stream
        for ch in self.reply:
            yield AIMessageChunk(content=ch)

    def with_structured_output(self, schema, method=None, **kwargs):
        self.structured_calls.append((schema, method))
        result = self.structured_result
        outer = self

        class _Runner:
            async def ainvoke(self, messages, **kwargs):
                outer.last_extract_messages = list(messages)
                return result

        return _Runner()


@pytest.fixture
def fake_model():
    return FakeModel()


@pytest.fixture
def client(fake_model):
    """注入 FakeModel 的 TestClient，并清空会话存储保证用例互不干扰。"""
    from fastapi.testclient import TestClient

    import app.main as main_module
    from app.api.routes import get_chat_model, store

    store.clear_all()
    main_module.app.dependency_overrides[get_chat_model] = lambda: fake_model
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()
    store.clear_all()
