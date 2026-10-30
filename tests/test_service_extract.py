from app.config import Settings
from app.memory import SessionStore
from app.schemas import AfterSaleIntent, AfterSaleRequest
from app.service import ChatService


def _service(fake_model, **overrides):
    settings = Settings(**{"llm_api_key": "test", **overrides})
    return ChatService(fake_model, SessionStore(), settings)


async def test_抽取走with_structured_output且schema正确(fake_model):
    fake_model.structured_result = AfterSaleRequest(
        order_id="SO20261029001", intent=AfterSaleIntent.EXCHANGE
    )
    svc = _service(fake_model)

    await svc.extract("订单 SO20261029001 太小了想换 L 码")

    schema, method = fake_model.structured_calls[-1]
    assert schema is AfterSaleRequest
    assert method == "function_calling"


async def test_抽取返回值是结构化对象(fake_model):
    fake_model.structured_result = AfterSaleRequest(
        order_id="SO20261029001", intent=AfterSaleIntent.EXCHANGE, confidence=0.8
    )
    svc = _service(fake_model)

    result = await svc.extract("订单 SO20261029001 太小了想换 L 码")

    assert isinstance(result, AfterSaleRequest)
    assert result.intent is AfterSaleIntent.EXCHANGE


async def test_抽取消息里带指令和原文(fake_model):
    fake_model.structured_result = AfterSaleRequest(intent=AfterSaleIntent.OTHER)
    svc = _service(fake_model)

    await svc.extract("我要退货")

    messages = fake_model.last_extract_messages
    assert messages[0].type == "system"
    assert "order_id" in messages[0].content
    assert messages[-1].content == "我要退货"


async def test_抽取方法可配置(fake_model):
    fake_model.structured_result = AfterSaleRequest(intent=AfterSaleIntent.OTHER)
    svc = _service(fake_model, structured_method="json_schema")

    await svc.extract("随便说点什么")

    assert fake_model.structured_calls[-1][1] == "json_schema"


async def test_把字符串null归一成None(fake_model):
    """模型常把空值写成字符串 "null"，不归一化会污染下游判空逻辑。"""
    fake_model.structured_result = AfterSaleRequest(
        order_id="null", intent=AfterSaleIntent.RETURN, reason="None", expected_solution=""
    )
    svc = _service(fake_model)

    result = await svc.extract("我要退货")

    assert result.order_id is None
    assert result.reason is None
    assert result.expected_solution is None


async def test_正常值不被归一化误伤(fake_model):
    fake_model.structured_result = AfterSaleRequest(
        order_id="SO20261029001", intent=AfterSaleIntent.RETURN, reason="尺码不合适"
    )
    svc = _service(fake_model)

    result = await svc.extract("我要退货")

    assert result.order_id == "SO20261029001"
    assert result.reason == "尺码不合适"
