"""测试共用夹具。

FakeModel 替代真实上游，不发任何网络请求。
数据库夹具懒加载：只有显式声明 engine / db_session 的用例才需要 MySQL，
其余用例不碰数据库，也不需要 Docker。
"""

import json

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessageChunk
from sqlalchemy import text

# 按外键依赖倒序清表
_CLEANUP_ORDER = ("messages", "tickets", "conversations", "faq")


class FakeModel:
    """满足 ChatService 所需的最小接口：astream + with_structured_output。"""

    def __init__(self, reply: str = "好的，我来帮您处理。"):
        self.reply = reply
        self.calls: list[list] = []              # 每次 astream 收到的消息
        self.structured_calls: list[tuple] = []  # (schema, method)
        self.structured_result = None
        self.last_extract_messages: list = []
        self.raise_on_stream: Exception | None = None
        # 工具流式调用相关的观测点，供 stream_with_tools 用例断言
        self.bound_names: list[list[str]] = []  # 每次 bind_tools 绑定的工具名
        self.stream_bounds: list[bool] = []     # 每次 astream 是否绑定了工具
        self.tool_calls_plan: list = []         # 预设第一趟要吐的 tool_calls
        self.preamble = ""                      # 第一趟调工具前先吐的正文
        self._plan_used = False

    async def astream(self, messages, **kwargs):
        self.calls.append(list(messages))
        self.stream_bounds.append(False)
        if self.raise_on_stream:
            raise self.raise_on_stream
        for ch in self.reply:
            yield AIMessageChunk(content=ch)

    def bind_tools(self, tools, **kwargs):
        self.bound_names.append([t.name for t in tools])
        outer = self

        class _BoundModel:
            """只实现 astream：模拟真实上游「绑定工具后」的流式行为。"""

            async def astream(self, messages, **kw):
                outer.calls.append(list(messages))
                outer.stream_bounds.append(True)
                if outer.raise_on_stream:
                    raise outer.raise_on_stream
                if outer.tool_calls_plan and not outer._plan_used:
                    outer._plan_used = True
                    # 真实上游常见行为：先应一句「我来帮您查一下」再发工具调用
                    for ch in outer.preamble:
                        yield AIMessageChunk(content=ch)
                    for chunk in outer._planned_tool_chunks():
                        yield chunk
                    return
                for ch in outer.reply:
                    yield AIMessageChunk(content=ch)

        return _BoundModel()

    def _planned_tool_chunks(self) -> list[AIMessageChunk]:
        """按真实上游的分片形状造工具调用：首片带 name/id，后续片只带 args 片段。"""
        chunks: list[AIMessageChunk] = []
        for index, plan in enumerate(self.tool_calls_plan):
            payload = json.dumps(plan["args"], ensure_ascii=False)
            third = max(1, len(payload) // 3)
            fragments = [
                payload[:third],
                payload[third : third * 2],
                payload[third * 2 :],
            ]
            for i, fragment in enumerate(fragments):
                chunks.append(
                    AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": plan["name"] if i == 0 else None,
                                "args": fragment,
                                "id": f"call_{index + 1}" if i == 0 else None,
                                "index": index,
                            }
                        ],
                    )
                )
        return chunks

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


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    """真 MySQL 引擎，整轮测试共用一个。

    只连测试库：夹具会清表，连演示库等于跑一次测试就清空演示数据。
    连不上时直接 pytest.exit，而不是让每条用例各抛一个断言失败——
    让开发者一眼看出是环境没起，不是代码坏了。
    """
    from app.core.config import get_settings
    from app.db.base import build_engine, create_all

    url = get_settings().test_database_url
    if not url:
        # 刻意不降级到 database_url：静默连演示库正是清空演示数据的成因
        pytest.exit("TEST_DATABASE_URL 未配置，测试会污染演示库，已中止", returncode=1)

    eng = build_engine(url)
    try:
        await create_all(eng)
    except Exception as exc:  # noqa: BLE001 - 任何连接/建表失败都归为环境问题
        await eng.dispose()
        pytest.exit(
            f"MySQL 不可达，请先执行 docker compose up -d\n目标: {url}\n原因: {exc}",
            returncode=1,
        )

    yield eng
    await eng.dispose()


async def _clean_tables(engine) -> None:
    """按外键顺序清空四张表。"""
    async with engine.begin() as conn:
        for table in _CLEANUP_ORDER:
            await conn.execute(text(f"DELETE FROM {table}"))


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(engine):
    """每个用例一个会话；用例前后都清表，断言不依赖库里的既有数据（如 seed 结果）。"""
    from app.db.base import build_sessionmaker

    # 先清一次：即使跑过 seed 或上一次的脏数据，用例也从空库开始
    await _clean_tables(engine)

    sessionmaker = build_sessionmaker(engine)
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            # 用例里可能 commit 过，也可能因 IntegrityError 处于失败态，统一回滚
            await session.rollback()

    await _clean_tables(engine)
