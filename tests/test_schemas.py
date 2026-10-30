import pytest
from pydantic import ValidationError

from app.schemas import AfterSaleIntent, AfterSaleRequest


def test_接受完整合法输入():
    req = AfterSaleRequest(
        order_id="SO20261029001",
        intent=AfterSaleIntent.RETURN,
        reason="尺码不合适",
        expected_solution="退货退款",
        missing_fields=[],
        confidence=0.9,
    )
    assert req.order_id == "SO20261029001"
    assert req.intent is AfterSaleIntent.RETURN


def test_订单号可以为空():
    req = AfterSaleRequest(intent=AfterSaleIntent.OTHER)
    assert req.order_id is None


def test_缺失字段默认为空列表():
    req = AfterSaleRequest(intent=AfterSaleIntent.EXCHANGE)
    assert req.missing_fields == []


def test_意图取值非法要报错():
    with pytest.raises(ValidationError):
        AfterSaleRequest(intent="退货")  # type: ignore[arg-type]


def test_置信度越界要报错():
    with pytest.raises(ValidationError):
        AfterSaleRequest(intent=AfterSaleIntent.RETURN, confidence=1.5)


def test_置信度默认是零():
    assert AfterSaleRequest(intent=AfterSaleIntent.RETURN).confidence == 0.0
