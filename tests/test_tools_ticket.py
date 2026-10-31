"""create_ticket 工具的行为测试。

tickets.conversation_id 是外键，所以每条用例先插一条 Conversation 拿真实 id。
conversation_id 由工厂闭包注入，工具的入参里不应该出现它。
"""

import re
from datetime import datetime

import pytest
from sqlalchemy import select

from app.db.models import Conversation, Ticket
from app.tools.ticket import make_create_ticket

# db_session 夹具跑在 session 级事件循环上，用例必须同循环，否则连接跨 loop 复用会报错
pytestmark = pytest.mark.asyncio(loop_scope="session")

_TICKET_NO_RE = re.compile(r"^TK\d{8}-\d{4}$")


async def _make_conversation(session, key: str = "sess-ticket-1") -> int:
    conv = Conversation(session_key=key, user_id="anon-1")
    session.add(conv)
    await session.commit()
    return conv.id


async def test_ticket_persisted_with_injected_conversation_id(db_session):
    """落库记录的 conversation_id 必须来自闭包，而不是模型入参。"""
    conv_id = await _make_conversation(db_session)

    tool = make_create_ticket(db_session, conv_id)
    result = await tool.ainvoke({"description": "收到的衣服有色差", "ticket_type": "退货"})

    rows = (await db_session.execute(select(Ticket))).scalars().all()
    assert len(rows) == 1
    assert rows[0].conversation_id == conv_id
    assert rows[0].description == "收到的衣服有色差"
    assert rows[0].ticket_type == "退货"
    assert rows[0].ticket_no == result["工单号"]
    assert result["状态"] == "open"
    assert result["提示"]


async def test_ticket_no_format(db_session):
    """工单号形如 TK20261031-0001。"""
    conv_id = await _make_conversation(db_session)

    tool = make_create_ticket(db_session, conv_id)
    result = await tool.ainvoke({"description": "快递一直没更新", "ticket_type": "物流异常"})

    assert _TICKET_NO_RE.match(result["工单号"]), result["工单号"]
    assert result["工单号"].startswith(f"TK{datetime.now():%Y%m%d}-")


async def test_ticket_no_increments_same_day(db_session):
    """同一天连续两张，序号递增不重复。"""
    conv_id = await _make_conversation(db_session)
    tool = make_create_ticket(db_session, conv_id)

    first = await tool.ainvoke({"description": "第一张", "ticket_type": "退货"})
    second = await tool.ainvoke({"description": "第二张", "ticket_type": "换货"})

    today = f"TK{datetime.now():%Y%m%d}-"
    assert first["工单号"] == f"{today}0001"
    assert second["工单号"] == f"{today}0002"


async def test_blank_description_raises(db_session):
    """描述为空直接抛 ValueError，交给 run_tool 封装，不写库。"""
    conv_id = await _make_conversation(db_session)

    tool = make_create_ticket(db_session, conv_id)
    with pytest.raises(ValueError, match="问题描述不能为空"):
        await tool.ainvoke({"description": "   ", "ticket_type": "其他"})

    rows = (await db_session.execute(select(Ticket))).scalars().all()
    assert rows == []


async def test_args_schema_excludes_conversation_id(db_session):
    """模型只能填 description / ticket_type。"""
    conv_id = await _make_conversation(db_session)

    tool = make_create_ticket(db_session, conv_id)
    props = tool.args_schema.model_json_schema()["properties"]

    assert set(props) == {"description", "ticket_type"}
    assert "conversation_id" not in props
