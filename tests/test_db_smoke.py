"""数据库冒烟测试：连真 MySQL，验证建表、中文存取、LIKE 召回与唯一约束。

不依赖 seed 状态，用例内自己插数据；db_session 结束后自动清表。
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import Conversation, Faq

# 数据库夹具跑在 session 级事件循环上，用例也用同一个循环，避免跨 loop 复用连接
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_faq_roundtrip_keeps_chinese(db_session, engine):
    """写入一条 FAQ 再查回来，中文不乱码。"""
    question = "退货运费谁承担？"
    answer = "质量问题、错发漏发由本店承担退货运费，七天无理由退货由买家承担。"

    db_session.add(Faq(question=question, answer=answer, category="售后"))
    await db_session.commit()

    # 用独立连接读，确保数据真的落库而不是从 ORM 身份映射里拿的
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT question, answer, category FROM faq WHERE question = :q"),
                {"q": question},
            )
        ).one()

    assert row.question == question
    assert row.answer == answer
    assert row.category == "售后"


async def test_like_finds_return_policy(db_session):
    """「退货政策」关键词能 LIKE 命中。"""
    db_session.add_all(
        [
            Faq(
                question="退货政策是什么？",
                answer="自签收之日起 7 天内，商品未拆封且不影响二次销售可申请无理由退货。",
                category="售后",
            ),
            Faq(
                question="下单后多久发货？",
                answer="现货商品付款后 48 小时内发出。",
                category="物流",
            ),
        ]
    )
    await db_session.commit()

    hit = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM faq "
                "WHERE question LIKE '%退货政策%' OR answer LIKE '%退货政策%'"
            )
        )
    ).scalar()

    assert hit == 1


async def test_like_youfei_returns_nothing(db_session):
    """「邮费」是刻意留的漏召回样本：种子里统一写作「运费」，所以查不出。"""
    db_session.add_all(
        [
            Faq(
                question="偏远地区运费怎么算？",
                answer="首重 1kg 收取 15 元，续重每公斤 8 元。",
                category="物流",
            ),
            Faq(
                question="退货运费谁承担？",
                answer="商品质量问题由本店承担退货运费。",
                category="售后",
            ),
        ]
    )
    await db_session.commit()

    miss = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM faq "
                "WHERE question LIKE '%邮费%' OR answer LIKE '%邮费%'"
            )
        )
    ).scalar()
    hit = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM faq "
                "WHERE question LIKE '%运费%' OR answer LIKE '%运费%'"
            )
        )
    ).scalar()

    assert miss == 0
    assert hit == 2


async def test_conversation_session_key_is_unique(db_session):
    """session_key 建了唯一索引，插两条相同值必须报 IntegrityError。"""
    db_session.add(Conversation(session_key="dup-session-key", user_id="anon-1"))
    await db_session.commit()

    db_session.add(Conversation(session_key="dup-session-key", user_id="anon-2"))
    with pytest.raises(IntegrityError):
        await db_session.commit()

    # 冲突后回滚，确认只有第一条落库
    await db_session.rollback()
    rows = (
        await db_session.execute(
            select(Conversation).where(Conversation.session_key == "dup-session-key")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == "anon-1"


async def test_engine_points_at_test_database(engine):
    """防回归：测试引擎必须连 shopmind_test，连演示库会被夹具清表清空。"""
    async with engine.connect() as conn:
        current = (await conn.execute(text("SELECT DATABASE()"))).scalar()

    assert current == "shopmind_test", f"测试连到了 {current}，演示库会被清空"
