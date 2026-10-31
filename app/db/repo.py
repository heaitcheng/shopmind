"""会话与消息的数据访问函数。

只做落库，不含业务判断；事务由调用方（或本模块的 append_turn）统一提交。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message


async def get_or_create_conversation(
    session: AsyncSession, session_key: str, user_id: str
) -> Conversation:
    """按 session_key 取会话，没有就建一条。

    两个请求同时首次进入时会都查不到然后都插入，后者撞唯一索引。
    这里吞掉 IntegrityError 并重查，调用方无需关心并发。

    注意：撞唯一索引时会 rollback，**整个事务**一起回滚。所以本函数必须
    在一个事务的最开始调用，不能放在已经写入了其他东西之后。
    """
    existing = (
        await session.execute(
            select(Conversation).where(Conversation.session_key == session_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    conv = Conversation(session_key=session_key, user_id=user_id, status="open")
    session.add(conv)
    try:
        await session.flush()
    except IntegrityError:
        # 别的事务抢先插入了同 key，回滚后重查必然能查到
        await session.rollback()
        return (
            await session.execute(
                select(Conversation).where(Conversation.session_key == session_key)
            )
        ).scalar_one()

    return conv


async def append_turn(
    session: AsyncSession,
    conversation_id: int,
    user_text: str,
    answer: str,
    tool_trace: list[dict],
) -> None:
    """写入一轮对话：user + assistant(+tool_calls) + 每个工具一条 tool 消息。"""
    session.add(
        Message(
            conversation_id=conversation_id,
            role="user",
            content=user_text,
            tool_calls=None,
            tool_call_id=None,
        )
    )

    tool_calls = [
        {"id": t["id"], "name": t["name"], "arguments": t["args"]} for t in tool_trace
    ] or None
    session.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            tool_calls=tool_calls,
        )
    )

    for t in tool_trace:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="tool",
                # 失败时写错误信息，查库就能看出这轮为什么没查到
                content=t["result"] if t["ok"] else t["error"],
                tool_call_id=t["id"],
            )
        )

    await session.commit()
