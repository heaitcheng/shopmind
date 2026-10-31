"""三个假数据业务工具的验收测试。

全部本地计算，不需要 Docker / MySQL / 网络。
"""

from app.tools.business import query_logistics, query_order, query_product


def test_query_order_same_id_returns_identical_dict():
    assert query_order.invoke({"order_id": 1001}) == query_order.invoke({"order_id": 1001})


def test_query_order_differs_across_ids():
    assert query_order.invoke({"order_id": 1001}) != query_order.invoke({"order_id": 1002})


def test_query_product_same_id_returns_identical_dict():
    assert query_product.invoke({"product_id": 2001}) == query_product.invoke(
        {"product_id": 2001}
    )


def test_query_product_differs_across_ids():
    assert query_product.invoke({"product_id": 2001}) != query_product.invoke(
        {"product_id": 2002}
    )


def test_query_logistics_same_id_returns_identical_dict():
    assert query_logistics.invoke({"order_id": 1001}) == query_logistics.invoke(
        {"order_id": 1001}
    )


def test_query_logistics_differs_across_ids():
    assert query_logistics.invoke({"order_id": 1001}) != query_logistics.invoke(
        {"order_id": 1002}
    )


def test_tool_names():
    assert query_order.name == "query_order"
    assert query_product.name == "query_product"
    assert query_logistics.name == "query_logistics"


def test_tool_descriptions_are_real_sentences():
    for tool in (query_order, query_product, query_logistics):
        assert len(tool.description) > 20


def test_waybill_is_derived_from_order_number():
    """运单号必须能看出和订单号的关联，不能是另一套随机数字。"""
    waybill = query_logistics.invoke({"order_id": 1001})["运单号"]
    assert "1001" in waybill
