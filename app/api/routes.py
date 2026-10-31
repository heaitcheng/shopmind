import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.llm import get_llm
from app.db.repo import append_turn, resolve_conversation
from app.db.session import get_session
from app.memory import SessionStore
from app.schemas import AfterSaleRequest
from app.service import ChatService
from app.tools.business import query_logistics, query_order, query_product
from app.tools.faq import make_query_faq
from app.tools.registry import ToolRegistry
from app.tools.ticket import make_create_ticket

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

router = APIRouter()

# 进程内会话表，与 ChatService 共享
store = SessionStore()


# ---- 依赖注入（测试里替换 get_chat_model 即可完全绕开网络）----


def get_chat_model():
    """配置类问题要变成可读的 503，而不是裸露的 500。"""
    try:
        return get_llm()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_service(
    model=Depends(get_chat_model), settings: Settings = Depends(get_settings)
) -> ChatService:
    return ChatService(model=model, store=store, settings=settings)


def build_registry(session, conversation_id) -> ToolRegistry:
    """把五个工具装进注册表。session 与 conversation_id 由调用方给，模型填不了。"""
    registry = ToolRegistry()
    registry.register(query_order)
    registry.register(query_product)
    registry.register(query_logistics)
    registry.register(make_query_faq(session))
    registry.register(make_create_ticket(session, conversation_id))
    return registry


def get_registry_factory():
    """返回「造注册表」的函数本身，测试里可整体替换掉。"""
    return build_registry


# ---- 请求体 ----


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    # 会话标识就是 conversations.id，首轮不带，后端建好后在 done 帧返回
    conversation_id: int | None = None
    user_id: str | None = None  # 无鉴权，前端生成的匿名 id


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1)


class ResetRequest(BaseModel):
    conversation_id: int


# ---- SSE 帧 ----


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---- 路由 ----


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    service: ChatService = Depends(get_service),
    session=Depends(get_session),
    make_registry=Depends(get_registry_factory),
):
    user_id = req.user_id or "anonymous"

    # 先建/取会话，拿到 conversation_id 才能造 create_ticket 工具
    conv = await resolve_conversation(session, req.conversation_id, user_id)
    # 进程内历史（SessionStore）按字符串 key 存，直接用会话主键
    store_key = str(conv.id)
    registry = make_registry(session, conv.id)

    # 复用 get_service 已解析好的 model/store/settings，只补 registry 与固定 id
    svc = ChatService(
        model=service.model,
        store=service.store,
        settings=service.settings,
        registry=registry,
        session_id_factory=lambda: store_key,
    )

    async def event_stream():
        try:
            async for item in svc.stream_with_tools(store_key, req.message):
                if item["event"] == "done":
                    # 对外只暴露会话主键：首轮拿不到，之后就靠它认会话
                    item["data"].pop("session_id", None)
                    item["data"]["conversation_id"] = conv.id
                    # 落库失败不能影响已经推给用户的内容，也不能吞得无声无息
                    try:
                        await append_turn(
                            session,
                            conv.id,
                            req.message,
                            item["data"]["content"],
                            item["data"]["tools"],
                        )
                    except Exception:
                        logger.warning("落库失败，本轮对话未持久化", exc_info=True)
                yield sse(item["event"], item["data"])
        except Exception as exc:  # 上游挂了也要让前端收到明确信号
            yield sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 让 nginx 不缓冲，否则流式失效
        },
    )


@router.post("/api/chat/extract", response_model=AfterSaleRequest)
async def chat_extract(req: ExtractRequest, service: ChatService = Depends(get_service)):
    return await service.extract(req.text)


@router.post("/api/chat/reset")
async def chat_reset(req: ResetRequest) -> dict:
    store.clear(str(req.conversation_id))
    return {"cleared": req.conversation_id}


@router.get("/")
async def index():
    page = STATIC_DIR / "index.html"
    if not page.exists():
        return JSONResponse({"detail": "聊天页面未生成"}, status_code=404)
    return FileResponse(page)
