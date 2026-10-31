"""query_faq 工具的行为测试。

连真 MySQL（db_session 指向 shopmind_test），每条用例自己插数据，
不依赖 seed 状态；用完由夹具清表。
"""

import pytest

from app.db.models import Faq
from app.tools.faq import make_query_faq

# db_session 夹具跑在 session 级事件循环上，用例必须同循环，否则连接跨 loop 复用会报错
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_keyword_hits_faq(db_session):
    """关键词能命中问题或答案里的内容。"""
    db_session.add(
        Faq(
            question="退货政策是什么？",
            answer="签收后 7 天内，商品未拆封且不影响二次销售可申请无理由退货。",
            category="售后",
        )
    )
    await db_session.commit()

    tool = make_query_faq(db_session)
    result = await tool.ainvoke({"keyword": "退货政策"})

    assert result["命中数"] >= 1
    assert result["条目"]
    assert "7 天" in result["条目"][0]["答案"]


async def test_youfei_miss_returns_hint(db_session):
    """「邮费」是刻意的漏召回样本：库里只写「运费」，查不到时必须给提示。"""
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

    tool = make_query_faq(db_session)
    result = await tool.ainvoke({"keyword": "邮费"})

    assert result["命中数"] == 0
    assert result["条目"] == []
    # 给模型看的护栏，不能被省略
    assert "提示" in result
    assert "不要编造" in result["提示"]


async def test_hits_capped_at_three(db_session):
    """命中多条时最多返回 3 条，且按 id 升序。"""
    db_session.add_all(
        [
            Faq(
                question=f"退货问题 {i}",
                answer=f"退货答案 {i}",
                category="售后",
            )
            for i in range(5)
        ]
    )
    await db_session.commit()

    tool = make_query_faq(db_session)
    result = await tool.ainvoke({"keyword": "退货"})

    assert result["命中数"] == 3
    assert len(result["条目"]) == 3
    # id 升序 => 问题 0/1/2
    assert [item["问题"] for item in result["条目"]] == [
        "退货问题 0",
        "退货问题 1",
        "退货问题 2",
    ]


async def test_blank_keyword_returns_zero_without_hitting_table(db_session):
    """空串或纯空格不查全表，直接返回 0 条。"""
    db_session.add(Faq(question="退货政策是什么？", answer="7 天无理由退货。", category="售后"))
    await db_session.commit()

    tool = make_query_faq(db_session)

    for keyword in ("", "   ", "\t\n "):
        result = await tool.ainvoke({"keyword": keyword})
        assert result["命中数"] == 0
        assert result["条目"] == []


async def test_item_fields(db_session):
    """条目的三个键必须齐全，模型才能直接读。"""
    db_session.add(
        Faq(question="退货政策是什么？", answer="7 天无理由退货。", category="售后")
    )
    await db_session.commit()

    tool = make_query_faq(db_session)
    result = await tool.ainvoke({"keyword": "退货"})

    item = result["条目"][0]
    assert set(item) == {"问题", "答案", "分类"}
    assert item["分类"] == "售后"
