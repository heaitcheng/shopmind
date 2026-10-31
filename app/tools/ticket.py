"""人工工单创建工具。

conversation_id 由工厂闭包注入，刻意不作为工具入参：模型编不出真实会话 id，
让它填只会往 tickets 表写脏数据或直接撞外键。
"""

from datetime import datetime
from typing import Literal

from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ticket

# Literal 让 args_schema 变成枚举，模型只能从中选一个
TicketType = Literal["退货", "换货", "退款", "物流异常", "其他"]

_CREATED_HINT = "工单已创建，人工客服会在 24 小时内联系用户"


def make_create_ticket(session: AsyncSession, conversation_id: int):
    """绑定会话与当前会话 id，返回可注册给模型的 create_ticket 工具。"""

    @tool
    async def create_ticket(description: str, ticket_type: TicketType) -> dict:
        """创建一张人工客服工单，把需要人工跟进的问题转出去。

        用户的问题 FAQ 查不到、或明确要求「转人工 / 投诉 / 找客服」时使用。
        description 写清用户遇到的具体问题（商品、订单号、诉求都要带上），
        不能为空；ticket_type 只能从 退货 / 换货 / 退款 / 物流异常 / 其他 中选一个。
        返回工单号、工单类型、状态和给用户的提示语。
        注意：当前会话 id 由系统自动带上，不需要也不能作为参数传入。
        """
        detail = description.strip()
        if not detail:
            # 不写库、不返回错误 dict：交给 run_tool 捕获并封装
            raise ValueError("问题描述不能为空")

        prefix = f"TK{datetime.now():%Y%m%d}-"
        existing = (
            (await session.execute(select(Ticket.ticket_no).where(Ticket.ticket_no.like(f"{prefix}%"))))
            .scalars()
            .all()
        )
        # 取当天已有最大值 + 1，从 0001 开始
        seq = max((int(no.rsplit("-", 1)[1]) for no in existing), default=0) + 1
        ticket_no = f"{prefix}{seq:04d}"

        ticket = Ticket(
            ticket_no=ticket_no,
            conversation_id=conversation_id,
            description=detail,
            ticket_type=ticket_type,
            status="open",
        )
        session.add(ticket)
        await session.commit()

        return {
            "工单号": ticket_no,
            "工单类型": ticket_type,
            "状态": ticket.status,
            "提示": _CREATED_HINT,
        }

    return create_ticket
