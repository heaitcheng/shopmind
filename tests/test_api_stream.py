import json


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """把 SSE 报文拆成 (事件名, data) 列表。"""
    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        events.append((name, data))
    return events


def test_健康检查(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_流式接口返回事件流类型(client):
    r = client.post("/api/chat/stream", json={"message": "我要退货"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")


def test_逐token推送并以done收尾(client, fake_model):
    fake_model.reply = "好的"
    r = client.post("/api/chat/stream", json={"message": "我要退货"})

    events = _parse_sse(r.text)
    names = [n for n, _ in events]

    assert names == ["token", "token", "done"]
    assert [d["delta"] for n, d in events if n == "token"] == ["好", "的"]


def test_done事件回传会话id(client, fake_model):
    r = client.post("/api/chat/stream", json={"message": "我要退货"})
    events = _parse_sse(r.text)
    done = events[-1][1]

    assert done["content"] == fake_model.reply
    assert done["session_id"]


def test_复用会话id能接住上文(client, fake_model):
    first = client.post("/api/chat/stream", json={"message": "我的订单是 SO20261029001"})
    sid = _parse_sse(first.text)[-1][1]["session_id"]

    client.post("/api/chat/stream", json={"session_id": sid, "message": "刚才那个订单号是多少"})

    joined = " ".join(str(m.content) for m in fake_model.calls[-1])
    assert "SO20261029001" in joined


def test_上游报错时发error事件而不是断连(client, fake_model):
    fake_model.raise_on_stream = RuntimeError("上游超时")
    r = client.post("/api/chat/stream", json={"message": "我要退货"})

    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert "上游超时" in events[-1][1]["message"]


def test_缺少message字段返回422(client):
    assert client.post("/api/chat/stream", json={}).status_code == 422


def test_清空会话只需session_id不要求message(client, fake_model):
    """页面上的清空按钮只发 session_id，早期版本误用了 ChatRequest 会 422。"""
    client.post("/api/chat/stream", json={"session_id": "s1", "message": "我要退货"})

    r = client.post("/api/chat/reset", json={"session_id": "s1"})

    assert r.status_code == 200
    assert r.json() == {"cleared": "s1"}


def test_清空后上下文不再延续(client, fake_model):
    client.post("/api/chat/stream", json={"session_id": "s1", "message": "我的订单是 SO20261029001"})
    client.post("/api/chat/reset", json={"session_id": "s1"})

    client.post("/api/chat/stream", json={"session_id": "s1", "message": "接着说"})

    joined = " ".join(str(m.content) for m in fake_model.calls[-1])
    assert "SO20261029001" not in joined
