"""stream_with_tools 的单轮工具编排测试。

全部走 FakeModel + 假工具：不发网络请求、不碰数据库。
"""

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from app.core.config import Settings
from app.memory import SessionStore
from app.service import ChatService
from app.tools.registry import ToolRegistry


@tool
async def fake_logistics(order_id: int) -> dict:
    """按订单号查物流。"""
    return {"当前状态": "派送中", "运单号": f"SF{order_id:010d}"}


@tool
async def fake_order(order_id: int) -> dict:
    """按订单号查订单。"""
    return {"订单号": f"SO{order_id:08d}", "金额": 199.0}


@tool
async def boom(order_id: int) -> dict:
    """永远失败的工具。"""
    raise RuntimeError("下游服务超时")


def _registry(*tools) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def _service(fake_model, registry=None) -> ChatService:
    return ChatService(
        fake_model,
        SessionStore(),
        Settings(llm_api_key="test"),
        registry=registry,
    )


async def _collect(gen):
    return [item async for item in gen]


def _kinds(events) -> list[str]:
    return [e["event"] for e in events]


def _tools(events) -> list[dict]:
    return [e["data"] for e in events if e["event"] == "tool"]


async def test_无工具调用时只发token和done(fake_model):
    fake_model.reply = "您好"
    svc = _service(fake_model, _registry(fake_logistics))

    events = await _collect(svc.stream_with_tools("s1", "你好"))

    assert _kinds(events) == ["token", "token", "done"]
    assert events[-1]["data"]["tools"] == []
    assert _tools(events) == []


async def test_有工具调用时事件顺序正确(fake_model):
    fake_model.reply = "已送达"
    fake_model.tool_calls_plan = [
        {"name": "fake_logistics", "args": {"order_id": 1001}}
    ]
    svc = _service(fake_model, _registry(fake_logistics))

    events = await _collect(svc.stream_with_tools("s1", "订单 1001 到哪了"))

    kinds = _kinds(events)
    assert kinds[:2] == ["tool", "tool"]
    assert [t["status"] for t in _tools(events)] == ["running", "ok"]
    assert kinds[-1] == "done"
    # 第二趟的正文必须在两次 tool 帧之后才吐
    last_tool_at = max(i for i, k in enumerate(kinds) if k == "tool")
    first_token_at = kinds.index("token")
    assert first_token_at > last_tool_at
    assert events[-1]["data"]["content"] == "已送达"


async def test_第二趟不绑定工具(fake_model):
    fake_model.reply = "好的"
    fake_model.tool_calls_plan = [
        {"name": "fake_logistics", "args": {"order_id": 1001}}
    ]
    svc = _service(fake_model, _registry(fake_logistics))

    await _collect(svc.stream_with_tools("s1", "查物流"))

    assert fake_model.stream_bounds == [True, False]


async def test_第一趟绑定全部已注册工具(fake_model):
    fake_model.reply = "好的"
    svc = _service(fake_model, _registry(fake_logistics, fake_order))

    await _collect(svc.stream_with_tools("s1", "你好"))

    assert set(fake_model.bound_names[0]) == {"fake_logistics", "fake_order"}


async def test_工具执行失败时回灌禁止编造的系统提示(fake_model):
    fake_model.reply = "这次没查到"
    fake_model.tool_calls_plan = [{"name": "boom", "args": {"order_id": 1001}}]
    svc = _service(fake_model, _registry(boom))

    events = await _collect(svc.stream_with_tools("s1", "查物流"))

    failed = _tools(events)[-1]
    assert failed["status"] == "error"
    assert "下游服务超时" in failed["error"]

    second_pass = fake_model.calls[-1]
    guards = [
        m for m in second_pass if isinstance(m, SystemMessage) and "不许编造" in m.content
    ]
    assert len(guards) == 1
    # 失败说明也回灌给了模型
    tool_msgs = [m for m in second_pass if isinstance(m, ToolMessage)]
    assert tool_msgs[0].content == "下游服务超时"


async def test_未知工具名只报错不中断整轮(fake_model):
    fake_model.reply = "抱歉"
    fake_model.tool_calls_plan = [{"name": "query_nothing", "args": {}}]
    svc = _service(fake_model, _registry(fake_logistics))

    events = await _collect(svc.stream_with_tools("s1", "帮我查一下"))

    failed = [t for t in _tools(events) if t["status"] == "error"]
    assert len(failed) == 1
    assert "未知工具" in failed[0]["error"]
    assert _kinds(events)[-1] == "done"
    assert events[-1]["data"]["tools"][0]["ok"] is False


async def test_done帧带完整工具轨迹(fake_model):
    fake_model.reply = "ok"
    fake_model.tool_calls_plan = [
        {"name": "fake_logistics", "args": {"order_id": 1001}}
    ]
    svc = _service(fake_model, _registry(fake_logistics))

    done = (await _collect(svc.stream_with_tools("s1", "查物流")))[-1]["data"]

    assert len(done["tools"]) == 1
    item = done["tools"][0]
    assert item == {
        "name": "fake_logistics",
        "args": {"order_id": 1001},
        "ok": True,
        "elapsed_ms": item["elapsed_ms"],
        "error": None,
    }
    assert isinstance(item["elapsed_ms"], int)


async def test_两个工具都执行且顺序对应(fake_model):
    fake_model.reply = "都查到了"
    fake_model.tool_calls_plan = [
        {"name": "fake_logistics", "args": {"order_id": 1001}},
        {"name": "fake_order", "args": {"order_id": 1002}},
    ]
    svc = _service(fake_model, _registry(fake_logistics, fake_order))

    events = await _collect(svc.stream_with_tools("s1", "查两个订单"))
    frames = _tools(events)

    assert [f["status"] for f in frames] == ["running", "ok", "running", "ok"]
    assert [f["name"] for f in frames] == [
        "fake_logistics",
        "fake_logistics",
        "fake_order",
        "fake_order",
    ]
    assert [t["name"] for t in events[-1]["data"]["tools"]] == [
        "fake_logistics",
        "fake_order",
    ]
    assert len(events[-1]["data"]["tools"]) == 2


async def test_历史只落两条消息不含ToolMessage(fake_model):
    fake_model.reply = "已送达"
    fake_model.tool_calls_plan = [
        {"name": "fake_logistics", "args": {"order_id": 1001}}
    ]
    svc = _service(fake_model, _registry(fake_logistics))

    await _collect(svc.stream_with_tools("s1", "查物流"))
    history = svc.store.get("s1")

    assert len(history) == 2
    assert isinstance(history[0], HumanMessage)
    assert history[0].content == "查物流"
    assert not any(isinstance(m, ToolMessage) for m in history)
    assert history[1].content == "已送达"


async def test_第一趟先应一句再调工具(fake_model):
    """真实上游会先说「我来帮您查一下」再发工具调用，两段都要进最终 answer。"""
    fake_model.preamble = "我先帮您查一下这单。"
    fake_model.tool_calls_plan = [{"name": "fake_logistics", "args": {"order_id": 1001}}]
    svc = _service(fake_model, _registry(fake_logistics))

    events = await _collect(svc.stream_with_tools("s1", "1001 的快递到哪了"))

    kinds = _kinds(events)
    first_tool = kinds.index("tool")
    last_tool = len(kinds) - 1 - kinds[::-1].index("tool")

    # 骨架：第一段 token → tool running → tool ok → 第二段 token → done
    assert set(kinds[:first_tool]) == {"token"}
    assert kinds[last_tool + 1 : -1] and set(kinds[last_tool + 1 : -1]) == {"token"}
    assert kinds[-1] == "done"

    first_stage = "".join(e["data"]["delta"] for e in events[:first_tool])
    second_stage = "".join(e["data"]["delta"] for e in events[last_tool + 1 : -1])

    assert first_stage == fake_model.preamble
    assert second_stage == fake_model.reply
    assert events[-1]["data"]["content"] == fake_model.preamble + fake_model.reply


async def test_第一趟前导空白被吃掉(fake_model):
    """有 assistant 历史时模型会在正文前吐换行，第一趟也要吃掉。"""
    fake_model.preamble = "\n\n我先帮您查一下。"
    fake_model.tool_calls_plan = [{"name": "fake_logistics", "args": {"order_id": 1001}}]
    svc = _service(fake_model, _registry(fake_logistics))

    events = await _collect(svc.stream_with_tools("s1", "查物流"))

    deltas = [e["data"]["delta"] for e in events if e["event"] == "token"]
    assert deltas, "应该有 token"
    assert not deltas[0][:1].isspace(), f"首个 token 不该以空白开头: {deltas[0]!r}"


async def test_第一趟正文与工具调用都进历史(fake_model):
    """历史里只留 Human + AI，中间的 ToolMessage 不落盘。"""
    fake_model.preamble = "我先查一下。"
    fake_model.tool_calls_plan = [{"name": "fake_logistics", "args": {"order_id": 1001}}]
    store = SessionStore()
    svc = ChatService(fake_model, store, Settings(llm_api_key="test"),
                      registry=_registry(fake_logistics))

    await _collect(svc.stream_with_tools("s1", "查物流"))

    history = store.get("s1")
    assert len(history) == 2
    assert isinstance(history[0], HumanMessage)
    assert not any(isinstance(m, ToolMessage) for m in history)
