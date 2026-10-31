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


_LEGAL_PAIRS = {
    ("已发货", "已揽收"),
    ("已发货", "运输中"),
    ("已发货", "派送中"),
    ("已完成", "已签收"),
    ("已退款", "已揽收"),  # 刚发出就退款，包裹被拦截
    ("已退款", "运输中"),
    ("已退款", "派送中"),
    ("已退款", "已签收"),
}


def test_order_status_matches_logistics_stage():
    """订单状态与物流阶段必须自洽。

    两个工具各自随机会造出「待发货 + 已签收」这种矛盾，演示时一眼就露馅。
    """
    for oid in range(1001, 1051):
        order_status = query_order.invoke({"order_id": oid})["订单状态"]
        stage = query_logistics.invoke({"order_id": oid})["当前状态"]
        assert (order_status, stage) in _LEGAL_PAIRS, (
            f"订单 {oid} 状态矛盾：{order_status} vs {stage}"
        )


def test_logistics_stage_stable_per_order():
    """同一订单的物流阶段多次查询必须一致，否则订单状态会跟着漂。"""
    for oid in (1001, 1002, 1007):
        first = query_logistics.invoke({"order_id": oid})["当前状态"]
        second = query_logistics.invoke({"order_id": oid})["当前状态"]
        assert first == second
