"""全局异步引擎与会话工厂。

引擎懒加载：模块导入时不建任何连接，第一次调用 get_engine() 才读配置。
这样跑测试（只连 test_database_url）不会顺带连上演示库。
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.base import build_engine, build_sessionmaker


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """进程级单例引擎，连演示库。"""
    url = get_settings().database_url
    if not url:
        # 刻意不降级到默认值：连错库比启动失败更难查
        raise RuntimeError("未配置 DATABASE_URL，请复制 .env.example 为 .env")
    return build_engine(url)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return build_sessionmaker(get_engine())


def _reset_engine_for_tests() -> None:
    """清掉单例，供测试隔离用；生产代码不要调用。"""
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


async def dispose_engine() -> None:
    """关闭引擎并清掉单例，重复调用无副作用。"""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    _reset_engine_for_tests()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，出错回滚。"""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
