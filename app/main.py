import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.llm import get_llm
from app.memory import SessionStore
from app.schemas import AfterSaleRequest
from app.service import ChatService

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="shopmind 智能客服", version="0.1.0")

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


# ---- 请求体 ----


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1)


# ---- SSE 帧 ----


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---- 路由 ----


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, service: ChatService = Depends(get_service)):
    async def event_stream():
        try:
            async for item in service.stream(req.session_id, req.message):
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


@app.post("/api/chat/extract", response_model=AfterSaleRequest)
async def chat_extract(req: ExtractRequest, service: ChatService = Depends(get_service)):
    return await service.extract(req.text)


@app.post("/api/chat/reset")
async def chat_reset(req: ChatRequest, ) -> dict:
    store.clear(req.session_id or "")
    return {"cleared": req.session_id}


@app.get("/")
async def index():
    page = STATIC_DIR / "index.html"
    if not page.exists():
        return JSONResponse({"detail": "聊天页面未生成"}, status_code=404)
    return FileResponse(page)
