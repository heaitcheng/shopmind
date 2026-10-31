"""接口层的工具调用协议与落库装配。

全程不连 MySQL：会话、落库、注册表工厂三个依赖都在本文件内替换掉。
落库逻辑本身的真实性由 tests/test_repo.py 覆盖，这里只验协议与装配。
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.tools import tool

import app.api.routes as routes
from app.api.routes import get_chat_model, get_registry_factory, store
from app.db.session import get_session
from app.tools.registry import ToolRegistry


@tool
def fake_logistics(order_id: int) -> dict:
    """按订单号查物流进度。"""
    return {"运单号": f"SF{order_id:010d}", "当前状态": "运输中"}


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """把 SSE 报文拆成 (事件名, data) 列表。"""
    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        events.append((name, data))
    return events


@pytest.fixture
def tool_client(monkeypatch, fake_model):
    """不连库的 TestClient：会话、落库、注册表工厂全部替换。"""
    recorded = {"appended": [], "conv": None, "fail_append": False}

    async def fake_get_or_create(session, session_key, user_id):
        recorded["conv"] = (session_key, user_id)

        class _C:
            id = 42

        return _C()

    async def fake_append_turn(session, conv_id, user_text, answer, tool_trace):
        if recorded["fail_append"]:
            raise RuntimeError("数据库断了")
        recorded["appended"].append(
            {
                "conv_id": conv_id,
                "user": user_text,
                "answer": answer,
                "tools": tool_trace,
            }
        )

    monkeypatch.setattr(routes, "get_or_create_conversation", fake_get_or_create)
    monkeypatch.setattr(routes, "append_turn", fake_append_turn)

    def fake_registry(session, conversation_id):
        registry = ToolRegistry()
        registry.register(fake_logistics)
        return registry

    store.clear_all()
    # 刻意不用 app.main.app：那是带 lifespan 的实例，会去连真实数据库
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_chat_model] = lambda: fake_model
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_registry_factory] = lambda: fake_registry

    with TestClient(app) as client:
        yield client, recorded

    store.clear_all()


def _plan_logistics(fake_model) -> None:
    fake_model.preamble = "我帮您查一下。"
    fake_model.tool_calls_plan = [
        {"name": "fake_logistics", "args": {"order_id": 1001}}
    ]


def test_流式响应里能拿到工具的running与ok两种帧(tool_client, fake_model):
    client, _ = tool_client
    _plan_logistics(fake_model)

    r = client.post("/api/chat/stream", json={"message": "查物流", "session_id": "s1"})

    assert r.status_code == 200
    tool_frames = [d for name, d in _parse_sse(r.text) if name == "tool"]
    statuses = [frame["status"] for frame in tool_frames]
    assert "running" in statuses
    assert "ok" in statuses
    assert tool_frames[-1]["name"] == "fake_logistics"


def test_done帧包含四个约定字段且回传请求里的session_id(tool_client):
    client, _ = tool_client

    r = client.post("/api/chat/stream", json={"message": "我要退货", "session_id": "s1"})
    done = _parse_sse(r.text)[-1]

    assert done[0] == "done"
    assert set(done[1]) == {"content", "session_id", "trimmed", "tools"}
    assert done[1]["session_id"] == "s1"


def test_客户端传session_id时沿用该值(tool_client):
    client, recorded = tool_client

    r = client.post(
        "/api/chat/stream", json={"message": "我要退货", "session_id": "s-abc"}
    )
    done = _parse_sse(r.text)[-1][1]

    assert done["session_id"] == "s-abc"
    assert recorded["conv"][0] == "s-abc"


def test_不传session_id时自动生成且与落库用的一致(tool_client):
    client, recorded = tool_client

    r = client.post("/api/chat/stream", json={"message": "我要退货"})
    done = _parse_sse(r.text)[-1][1]

    assert isinstance(done["session_id"], str)
    assert done["session_id"]
    assert recorded["conv"][0] == done["session_id"]


def test_完成后把本轮对话落库(tool_client, fake_model):
    client, recorded = tool_client
    _plan_logistics(fake_model)

    r = client.post("/api/chat/stream", json={"message": "查物流", "session_id": "s1"})
    done = _parse_sse(r.text)[-1][1]

    assert len(recorded["appended"]) == 1
    saved = recorded["appended"][0]
    assert saved["conv_id"] == 42
    assert saved["user"] == "查物流"
    assert saved["answer"] == done["content"]
    assert saved["tools"]
    assert saved["tools"][0]["name"] == "fake_logistics"


def test_落库失败不影响已推给客户端的内容(tool_client):
    client, recorded = tool_client
    recorded["fail_append"] = True

    r = client.post("/api/chat/stream", json={"message": "我要退货", "session_id": "s1"})
    events = _parse_sse(r.text)

    assert r.status_code == 200
    assert "error" not in [name for name, _ in events]
    assert events[-1][0] == "done"
    assert events[-1][1]["session_id"] == "s1"
