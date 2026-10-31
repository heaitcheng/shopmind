from langchain_core.messages import HumanMessage

from app.config import Settings
from app.memory import SessionStore
from app.service import ChatService


def _service(fake_model, **overrides):
    settings = Settings(**{"llm_api_key": "test", **overrides})
    return ChatService(fake_model, SessionStore(), settings)


async def _collect(gen):
    return [item async for item in gen]


async def test_逐字推送后以done收尾(fake_model):
    fake_model.reply = "好的"
    svc = _service(fake_model)

    events = await _collect(svc.stream(None, "我要退货"))

    kinds = [e["event"] for e in events]
    assert kinds == ["token", "token", "done"]
    assert [e["data"]["delta"] for e in events[:2]] == ["好", "的"]


async def test_done事件带回完整回复与会话id(fake_model):
    fake_model.reply = "我来帮您核实"
    svc = _service(fake_model)

    events = await _collect(svc.stream(None, "我要退货"))
    done = events[-1]["data"]

    assert done["content"] == "我来帮您核实"
    assert done["session_id"]
    assert done["trimmed"] == 0


async def test_第二轮能看到第一轮内容(fake_model):
    svc = _service(fake_model)

    first = await _collect(svc.stream("s1", "我的订单是 SO20261029001"))
    sid = first[-1]["data"]["session_id"]
    await _collect(svc.stream(sid, "那我刚才说的是哪个订单？"))

    second_call_messages = fake_model.calls[-1]
    joined = " ".join(str(m.content) for m in second_call_messages)
    assert "SO20261029001" in joined


async def test_system消息排在最前面(fake_model):
    svc = _service(fake_model, shop_name="测试小店")
    await _collect(svc.stream("s1", "你好"))

    messages = fake_model.calls[-1]
    assert messages[0].type == "system"
    assert "测试小店" in messages[0].content
    assert isinstance(messages[-1], HumanMessage)


async def test_流结束后才写历史(fake_model):
    svc = _service(fake_model)
    await _collect(svc.stream("s1", "我要退货"))
    assert len(svc.store.get("s1")) == 2  # 一轮用户 + 一轮客服


async def test_超预算时trimmed大于零(fake_model):
    svc = _service(fake_model, history_max_tokens=60)
    for i in range(6):
        await _collect(svc.stream("s1", f"第{i}次：我要退货，订单号 SO2026{i:04d}，尺码不合适"))

    events = await _collect(svc.stream("s1", "再问一次"))
    assert events[-1]["data"]["trimmed"] > 0


async def test_首个token不能是前导换行(fake_model):
    """有 assistant 历史时 GLM 会在回答前吐一个换行，推给前端就是一行空白。"""
    fake_model.reply = "\n\n您的订单号是 SO20261029001。"
    svc = _service(fake_model)

    events = await _collect(svc.stream("s1", "我刚才说的订单号是多少？"))

    first_delta = events[0]["data"]["delta"]
    assert first_delta.strip() != ""
    assert first_delta == "您"
    assert events[-1]["data"]["content"] == "您的订单号是 SO20261029001。"


async def test_回应中间的空行要保留(fake_model):
    """只吃前导空白，正文里的分段是正常排版，不能一起吃掉。"""
    fake_model.reply = "\n好的，分两步：\n\n第一，先确认订单；\n第二，再寄回。"
    svc = _service(fake_model)

    events = await _collect(svc.stream("s1", "怎么退货"))

    content = events[-1]["data"]["content"]
    assert content.startswith("好的")
    assert "\n\n第一" in content


async def test_首块全是空白时不产生空token事件(fake_model):
    fake_model.reply = "\n\n\n正文在这里"
    svc = _service(fake_model)

    events = await _collect(svc.stream("s1", "随便问"))

    tokens = [e for e in events if e["event"] == "token"]
    assert tokens[0]["data"]["delta"].strip() != ""
    # 连续的空白首块应被吞掉，不能变成多个空 token
    assert all(t["data"]["delta"].strip() != "" for t in tokens)
