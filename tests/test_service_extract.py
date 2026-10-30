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
