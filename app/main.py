import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.db.base import create_all
from app.db.session import dispose_engine, get_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    try:
        await create_all(get_engine())
    except Exception:
        # 无库时纯对话链路仍应可用，所以只告警不阻断启动
        logger.warning("数据库不可用，工具调用与对话落库将失败", exc_info=True)
    yield
    await dispose_engine()


app = FastAPI(title="shopmind 智能客服", version="0.1.0", lifespan=lifespan)
app.include_router(router)
