"""数据库引擎、会话工厂与建表工具。

模块导入时不做任何连接动作，一切由调用方显式构建。
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def build_engine(url: str):
    return create_async_engine(url, pool_pre_ping=True, pool_recycle=1800)


def build_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine) -> None:
    """建表。仅供本地开发与测试用，生产应换成迁移工具。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
