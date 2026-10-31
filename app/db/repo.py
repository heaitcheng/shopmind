"""会话与消息的数据访问函数。

只做落库，不含业务判断；事务由调用方（或本模块的 append_turn）统一提交。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message


async def resolve_conversation(
    session: AsyncSession, conversation_id: int | None, user_id: str
) -> Conversation:
    """拿到本轮该写进哪条会话。

    - 前端带了 id 且库里有：直接复用
    - 没带 id，或带了但库里没有（库被重建过、前端留着旧 id）：新建一条

    id 查不到时选择新建而不是报错，是为了让「清库后前端还存着旧 id」
    这种场景能自愈，不至于把用户卡死在报错上。
    """
    if conversation_id is not None:
        existing = await session.get(Conversation, conversation_id)
        if existing is not None:
            return existing

    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    await session.flush()
    # status / created_at 是服务端默认值，flush 后处于过期状态；
    # 不 refresh 的话调用方一读属性就会在 async 上下文里触发 IO 而报 MissingGreenlet
    await session.refresh(conversation)
    return conversation


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
