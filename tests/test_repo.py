"""会话仓库函数的行为测试。

全部走 db_session（测试库 shopmind_test），不碰演示库。
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DataError

from app.db.models import Conversation, Message
from app.db.repo import append_turn, resolve_conversation

# 夹具跑在 session 级事件循环上，用例必须同循环
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar()


async def test_不带id时新建会话且状态走服务端默认值(db_session):
    conv = await resolve_conversation(db_session, None, "anon-1")

    assert conv.id is not None
    assert conv.user_id == "anon-1"
    assert conv.status == "进行中"  # 服务端默认值，不是应用层写的
    assert await _count(db_session, Conversation) == 1


async def test_带已存在的id时复用同一条(db_session):
    first = await resolve_conversation(db_session, None, "anon-1")
    await db_session.commit()

    second = await resolve_conversation(db_session, first.id, "anon-2")

    assert second.id == first.id
    # 已存在时不更新任何字段
    assert second.user_id == "anon-1"
    assert await _count(db_session, Conversation) == 1


async def test_带不存在的id时新建一条(db_session):
    """库被重建、前端还留着旧 id：不能报错把用户卡死，按新会话处理。"""
    ghost = await resolve_conversation(db_session, 999999, "anon-1")

    assert ghost.id != 999999
    assert ghost.user_id == "anon-1"
    assert await _count(db_session, Conversation) == 1


async def test_连续两次不带id会建出两条(db_session):
    a = await resolve_conversation(db_session, None, "anon-1")
    await db_session.commit()
    b = await resolve_conversation(db_session, None, "anon-1")

    assert a.id != b.id
    assert await _count(db_session, Conversation) == 2


async def test_会话状态只接受枚举内的值(db_session):
    """DDL 里 status 是 ENUM，越界值必须在数据库层被拒，不靠应用层自觉。"""
    with pytest.raises(DataError):
        db_session.add(Conversation(user_id="anon-1", status="open"))  # 旧值，已不在枚举里
        await db_session.flush()
    await db_session.rollback()


async def test_消息角色只接受枚举内的值(db_session):
    conv = await resolve_conversation(db_session, None, "anon-1")
    await db_session.commit()

    with pytest.raises(DataError):
        db_session.add(Message(conversation_id=conv.id, role="system", content="x"))
        await db_session.flush()
    await db_session.rollback()


async def test_append_turn_without_tools_writes_two_messages(db_session):
    """无工具调用：只有 user 与 assistant 两条，assistant 的 tool_calls 为空。"""
    conv = await resolve_conversation(db_session, None, "anon-1")
    await db_session.commit()

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
    conv = await resolve_conversation(db_session, None, "anon-1")
    await db_session.commit()
    trace = [
        {
            "id": "call_1",
            "name": "query_faq",
            "args": {"keyword": "退货政策"},
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
    assert calls[0]["name"] == "query_faq"
    assert calls[0]["id"] == "call_1"
    assert calls[0]["arguments"] == {"keyword": "退货政策"}

    assert rows[2].content == "7 天无理由退货"
    assert rows[2].tool_call_id == "call_1"


async def test_append_turn_records_tool_error_as_content(db_session):
    """工具失败时把错误信息写进 tool 消息，便于事后排查漏召回。"""
    conv = await resolve_conversation(db_session, None, "anon-1")
    await db_session.commit()
    trace = [
        {
            "id": "call_1",
            "name": "query_faq",
            "args": {"keyword": "邮费"},
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


async def test_没有工具调用时tool_calls是SQL_NULL而不是JSON_null(db_session):
    """两种空形态混用会让 `WHERE tool_calls IS NULL` 漏行。

    SQLAlchemy 的 JSON 类型默认把 None 序列化成 JSON 字面量 'null'，
    必须显式 none_as_null=True 才是真正的 SQL NULL。
    """
    from sqlalchemy import text

    conv = await resolve_conversation(db_session, None, "anon-1")
    await db_session.commit()

    await append_turn(db_session, conv.id, "在吗？", "在的。", [])

    n_null = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM messages WHERE tool_calls IS NULL")
        )
    ).scalar()
    assert n_null == 2, "user 与 assistant 两条都应是 SQL NULL"

    # 反向确认：没有一行存成 JSON 字面量 'null'
    n_json_null = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM messages WHERE JSON_TYPE(tool_calls) = 'NULL'")
        )
    ).scalar()
    assert n_json_null == 0
