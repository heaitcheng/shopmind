"""数据表模型，字段与本章 DDL 逐项对齐。

约定：
- 主键与外键统一 BIGINT UNSIGNED
- 状态、角色、类型用 MySQL ENUM，值域由数据库兜住，不靠应用层自觉
- 时间字段用服务端 ``CURRENT_TIMESTAMP``，不是 Python 侧赋值
- 全表 ENGINE=InnoDB + utf8mb4，否则中文会出问题

注释（COMMENT）不是装饰：``SHOW CREATE TABLE`` 时能直接看懂每个字段的用途，
省掉翻代码对字段语义的工夫。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 写成 text 而不是 func.now()：后者建出来的 DDL 是 DEFAULT (now())，
# 与 DDL 里的 DEFAULT CURRENT_TIMESTAMP 不是同一个写法。
_CREATED_AT = text("CURRENT_TIMESTAMP")
_UPDATED_AT = text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")


def _table_args(comment: str) -> dict:
    """每次返回新 dict，避免多个表共享同一份 table kwargs。"""
    return {
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
        "comment": comment,
    }


class Faq(Base):
    __tablename__ = "faq"
    __table_args__ = (Index("idx_category", "category"), _table_args("常见问答"))

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="FAQ 主键"
    )
    question: Mapped[str] = mapped_column(String(512), nullable=False, comment="问题")
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="答案")
    category: Mapped[str] = mapped_column(String(64), nullable=False, comment="分类")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=_CREATED_AT, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=_UPDATED_AT, comment="更新时间"
    )


class Conversation(Base):
    """会话壳。id 就是对外暴露的会话标识，前端在 done 帧里拿到后逐轮回传。"""

    __tablename__ = "conversations"
    __table_args__ = (Index("idx_user_id", "user_id"), _table_args("客服会话"))

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="会话主键"
    )
    # 无鉴权，存前端持有的匿名 id
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="用户标识")
    status: Mapped[str] = mapped_column(
        ENUM("进行中", "已转人工", "已结束", name="conv_status"),
        nullable=False,
        server_default="进行中",
        comment="处理状态",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=_CREATED_AT, comment="开启时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=_UPDATED_AT, comment="更新时间"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_conversation_id", "conversation_id"),
        _table_args("会话消息流水"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), primary_key=True, autoincrement=True, comment="消息主键"
    )
    conversation_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("conversations.id", name="fk_messages_conversation"),
        nullable=False,
        comment="所属会话",
    )
    role: Mapped[str] = mapped_column(
        ENUM("user", "assistant", "tool", name="msg_role"),
        nullable=False,
        comment="角色:用户/助手/工具结果",
    )
    # assistant 纯工具调用那一轮 content 为空
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="消息正文,assistant 纯工具调用时可为空"
    )
    # 形如 [{"id":..,"name":..,"arguments":{..}}]
    # none_as_null：让 None 落成 SQL NULL 而不是 JSON 字面量 'null'，
    # 否则 tool_calls IS NULL 永远查不到「没有工具调用」的行
    tool_calls: Mapped[list | dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True, comment="assistant 消息带的工具调用申请单"
    )
    tool_call_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="tool 消息对应的申请单 id,回灌时对号入座"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=_CREATED_AT, comment="产生时间"
    )


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("idx_conversation_id", "conversation_id"),
        _table_args("人工工单"),
    )

    # 业务主键，规则见 app/tools/ticket.py
    ticket_no: Mapped[str] = mapped_column(
        String(32), primary_key=True, comment="工单号"
    )
    conversation_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("conversations.id", name="fk_tickets_conversation"),
        nullable=False,
        comment="关联会话,可倒查当时聊了什么",
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="问题描述")
    ticket_type: Mapped[str] = mapped_column(
        ENUM("售后", "投诉", "咨询", name="ticket_type"),
        nullable=False,
        comment="工单类型",
    )
    status: Mapped[str] = mapped_column(
        ENUM("待处理", "已处理", name="ticket_status"),
        nullable=False,
        server_default="待处理",
        comment="处理状态",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=_CREATED_AT, comment="创建时间"
    )
