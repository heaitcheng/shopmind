"""FAQ 检索工具：按关键词在问题与答案上做 LIKE 匹配。

会话由工厂闭包注入，工具自己不建连、不 commit。
"""

from langchain_core.tools import tool
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Faq

# 一次最多给模型 3 条，避免把整张表塞进上下文
_MAX_HITS = 3

# 查不到时给模型的护栏。漏召回时让它自己编政策，比查不到更危险
_EMPTY_HINT = "FAQ 库中没有匹配条目，不要编造政策，建议转人工确认"


def make_query_faq(session: AsyncSession):
    """绑定会话，返回可注册给模型的 query_faq 工具。"""

    @tool
    async def query_faq(keyword: str) -> dict:
        """按关键词检索店铺常见问题（FAQ）库。

        当用户问退换货政策、运费、发货时效、发票、优惠券怎么用这类**通用规则**问题时使用。
        例如用户问「你们退货政策是什么」，就把「退货」或「退货政策」作为 keyword 传入。
        关键词会在问题与答案两个字段上做模糊匹配，返回命中条数和条目列表，
        每条含问题、答案、分类。
        命中数为 0 时会额外给出「提示」：此时不要凭空编造政策，应建议用户转人工确认。
        注意：本工具只查通用规则；查具体订单、商品、物流请改用对应工具。
        """
        kw = keyword.strip()
        if not kw:
            return {"命中数": 0, "条目": [], "提示": _EMPTY_HINT}

        pattern = f"%{kw}%"
        stmt = (
            select(Faq)
            .where(or_(Faq.question.like(pattern), Faq.answer.like(pattern)))
            .order_by(Faq.id)
            .limit(_MAX_HITS)
        )
        rows = (await session.execute(stmt)).scalars().all()

        items = [
            {"问题": row.question, "答案": row.answer, "分类": row.category} for row in rows
        ]
        if not items:
            return {"命中数": 0, "条目": [], "提示": _EMPTY_HINT}
        return {"命中数": len(items), "条目": items}

    return query_faq
