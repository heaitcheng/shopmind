from langchain_core.messages import AIMessage, HumanMessage

from app.memory import SessionStore, build_context, count_tokens


def _turns(n: int):
    msgs = []
    for i in range(n):
        msgs.append(HumanMessage(content=f"第{i}轮用户：我要退货，订单号 SO2026{i:04d}，理由是尺码不合适"))
        msgs.append(AIMessage(content=f"第{i}轮客服：好的，我来帮您核实这笔订单的退换货政策。"))
    return msgs


def test_空历史返回空且零裁剪():
    kept, trimmed = build_context([], 100)
    assert kept == []
    assert trimmed == 0


def test_超预算会裁剪并保留最近的内容():
    history = _turns(10)
    kept, trimmed = build_context(history, 120)

    assert len(kept) < len(history)
    assert trimmed == len(history) - len(kept)
    assert kept[-1].content == history[-1].content


def test_裁剪后必须以人类消息开头():
    history = _turns(10)
    kept, _ = build_context(history, 120)
    assert isinstance(kept[0], HumanMessage)


def test_预算充足时不裁剪():
    history = _turns(2)
    kept, trimmed = build_context(history, 100_000)
    assert len(kept) == len(history)
    assert trimmed == 0


def test_count_tokens_支持单条与列表():
    msg = HumanMessage(content="我要退货")
    assert count_tokens(msg) > 0
    assert count_tokens([msg, msg]) == count_tokens(msg) * 2


def test_会话存储_追加后可取回():
    store = SessionStore()
    assert store.get("s1") == []

    store.append("s1", [HumanMessage(content="一"), AIMessage(content="二")])
    store.append("s1", [HumanMessage(content="三")])

    got = store.get("s1")
    assert len(got) == 3
    assert got[-1].content == "三"


def test_会话存储_未知id返回空():
    assert SessionStore().get("不存在") == []


def test_会话存储_清空():
    store = SessionStore()
    store.append("s1", [HumanMessage(content="一")])
    store.clear("s1")
    assert store.get("s1") == []


def test_会话存储_取回的是副本():
    store = SessionStore()
    store.append("s1", [HumanMessage(content="一")])
    store.get("s1").append(HumanMessage(content="偷偷塞进去"))
    assert len(store.get("s1")) == 1
