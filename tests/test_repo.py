"""会话仓库函数的行为测试。

全部走 db_session（测试库 shopmind_test），不碰演示库。
"""

import pytest
from sqlalchemy import func, select

from app.db.models import Conversation, Message
from app.db.repo import append_turn, get_or_create_conversation

# 夹具跑在 session 级事件循环上，用例必须同循环
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar()


async def test_get_or_create_returns_same_row_for_same_key(db_session):
    """同一个 session_key 第二次调用返回同一条，且库里只有 1 条。"""
    first = await get_or_create_conversation(db_session, "sess-1", "anon-1")
    second = await get_or_create_conversation(db_session, "sess-1", "anon-2")

    assert first.id == second.id
    # 已存在时不更新任何字段
    assert second.user_id == "anon-1"
    assert await _count(db_session, Conversation) == 1


async def test_get_or_create_creates_distinct_rows_for_distinct_keys(db_session):
    """不同 session_key 各自建一条，status 默认为 open。"""
    a = await get_or_create_conversation(db_session, "sess-a", "anon-1")
    b = await get_or_create_conversation(db_session, "sess-b", "anon-1")

    assert a.id != b.id
    assert a.status == "open"
    assert await _count(db_session, Conversation) == 2


async def test_append_turn_without_tools_writes_two_messages(db_session):
    """无工具调用：只有 user 与 assistant 两条，assistant 的 tool_calls 为空。"""
    conv = await get_or_create_conversation(db_session, "sess-plain", "anon-1")

    await append_turn(db_session, conv.id, "在吗？", "在的，请问有什么可以帮您？", [])

    rows = (
        await db_session.execute(select(Message).order_by(Message.id))
    ).scalars().all()
    assert len(rows) == 2
    assert [m.role for m in rows] == ["user", "assistant"]
    assert rows[0].content == "在吗？"
    assert rows[0].tool_calls is None
    assert rows[0].tool_call_id is None
    assert rows[1].content == "在的，请问有什么可以帮您？"
    assert rows[1].tool_calls is None


async def test_append_turn_with_tool_writes_three_messages(db_session):
    """有工具调用：assistant 记录 tool_calls，tool 消息按 id 回填。"""
    conv = await get_or_create_conversation(db_session, "sess-tool", "anon-1")
    trace = [
        {
            "id": "call_1",
            "name": "search_faq",
            "args": {"query": "退货政策"},
            "ok": True,
            "elapsed_ms": 12,
            "error": None,
            "result": "7 天无理由退货",
        }
    ]

    await append_turn(db_session, conv.id, "能退货吗？", "可以的。", trace)

    rows = (
        await db_session.execute(select(Message).order_by(Message.id))
    ).scalars().all()
    assert [m.role for m in rows] == ["user", "assistant", "tool"]

    calls = rows[1].tool_calls
    assert isinstance(calls, list) and len(calls) == 1
    assert calls[0]["name"] == "search_faq"
    assert calls[0]["id"] == "call_1"
    assert calls[0]["arguments"] == {"query": "退货政策"}

    assert rows[2].content == "7 天无理由退货"
    assert rows[2].tool_call_id == "call_1"


async def test_append_turn_records_tool_error_as_content(db_session):
    """工具失败时把错误信息写进 tool 消息，便于事后排查漏召回。"""
    conv = await get_or_create_conversation(db_session, "sess-fail", "anon-1")
    trace = [
        {
            "id": "call_1",
            "name": "search_faq",
            "args": {"query": "邮费"},
            "ok": False,
            "elapsed_ms": 5001,
            "error": "工具执行超时",
            "result": None,
        }
    ]

    await append_turn(db_session, conv.id, "邮费多少？", "稍等。", trace)

    tool_msg = (
        await db_session.execute(select(Message).where(Message.role == "tool"))
    ).scalar_one()
    assert tool_msg.content == "工具执行超时"
    assert tool_msg.content


async def test_conflict_falls_back_to_existing_row(db_session, engine, monkeypatch):
    """并发撞唯一索引：捕获 IntegrityError 回滚后重查，返回已有记录。

    用「本事务先读一次建立快照 + 另一个连接抢先插入并提交」造出真实的竞态，
    此时本事务的 SELECT 看不到新行，flush 必然抛 IntegrityError。
    """
    from app.db.base import build_sessionmaker

    await db_session.execute(select(Conversation.id))  # 固定当前事务的读视图

    async with build_sessionmaker(engine)() as rival_session:
        rival = Conversation(session_key="sess-race", user_id="winner")
        rival_session.add(rival)
        await rival_session.commit()
        rival_id = rival.id

    rolled_back = []
    original_rollback = db_session.rollback

    async def spy_rollback():
        rolled_back.append(True)
        await original_rollback()

    monkeypatch.setattr(db_session, "rollback", spy_rollback)

    conv = await get_or_create_conversation(db_session, "sess-race", "loser")

    assert conv.id == rival_id
    assert conv.user_id == "winner"
    assert rolled_back == [True], "没有走到 IntegrityError 回滚分支"
    assert await _count(db_session, Conversation) == 1
