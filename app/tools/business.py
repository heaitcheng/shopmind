"""假数据业务工具：订单、商品、物流。

全部用固定种子的 random.Random 生成，同一个 id 永远返回同一份内容；
不连数据库、不发网络请求、不依赖 sqlalchemy。
"""

import random
from datetime import datetime, timedelta

from langchain_core.tools import tool

# 固定基准时间，避免 datetime.now() 让返回值随运行时刻变化
_BASE_TIME = datetime(2026, 1, 1, 9, 0, 0)

_PRODUCTS = [
    ("轻氧棉麻宽松衬衫", 189.0, "亚麻 55% / 棉 45%", "S / M / L / XL"),
    ("复古水洗牛仔直筒裤", 259.0, "100% 棉牛仔布", "26 / 27 / 28 / 29 / 30"),
    ("云感软糯针织开衫", 329.0, "羊毛混纺", "S / M / L"),
    ("极简纯棉基础T恤", 89.0, "100% 新疆长绒棉", "S / M / L / XL / XXL"),
    ("防风立领冲锋衣", 599.0, "聚酯纤维 + 氨纶", "M / L / XL / XXL"),
    ("高腰垂感阔腿西裤", 279.0, "莱赛尔混纺", "S / M / L / XL"),
]

_CITIES = ["上海市", "北京市", "杭州市", "成都市", "广州市", "武汉市", "南京市", "西安市"]

_ORDER_STATUSES = ["待发货", "已发货", "已完成", "已退款"]

# (承运商, 运单号前缀)
_CARRIERS = [("顺丰", "SF"), ("中通", "ZTO"), ("圆通", "YTO"), ("京东物流", "JD")]

_LOGISTICS_STAGES = ["已揽收", "运输中", "派送中", "已签收"]


def _format_time(offset_days: int, offset_hours: int, offset_minutes: int) -> str:
    moment = _BASE_TIME + timedelta(
        days=offset_days, hours=offset_hours, minutes=offset_minutes
    )
    return moment.strftime("%Y-%m-%d %H:%M:%S")


@tool
def query_order(order_id: int) -> dict:
    """按订单号查询订单详情。

    用户在问「我买的什么、花了多少钱、订单到哪一步了、什么时候下的单」时使用。
    例如用户说「帮我查下订单 1001」，就调用本工具，把 1001 作为 order_id 传入。
    返回订单号、下单时间、商品名、数量、金额、订单状态和收货城市。
    注意：order_id 只能是纯数字订单编号；查物流进度请改用 query_logistics。
    """
    rng = random.Random(order_id)

    name, unit_price, _material, _spec = _PRODUCTS[rng.randrange(len(_PRODUCTS))]
    quantity = rng.randint(1, 3)
    amount = round(unit_price * quantity, 2)
    status = _ORDER_STATUSES[rng.randrange(len(_ORDER_STATUSES))]
    city = _CITIES[rng.randrange(len(_CITIES))]

    return {
        "订单号": f"SO{order_id:08d}",
        "下单时间": _format_time(
            rng.randint(0, 45), rng.randint(0, 23), rng.randint(0, 59)
        ),
        "商品名": name,
        "数量": quantity,
        "金额": amount,
        "订单状态": status,
        "收货城市": city,
    }


@tool
def query_product(product_id: int) -> dict:
    """按商品编号查询商品的在售信息。

    用户在问「这件商品多少钱、还有没有货、有什么尺码、什么材质、什么时候上架的」
    时使用。例如用户说「商品 2001 什么价」，就调用本工具，把 2001 作为 product_id 传入。
    返回商品名、价格、库存、规格尺码、材质和上架时间。
    注意：product_id 是商品编号，不是订单号。
    """
    rng = random.Random(product_id)

    name, base_price, material, spec = _PRODUCTS[rng.randrange(len(_PRODUCTS))]
    # 活动价允许在基准价上下浮动，但同一商品始终一致
    price = round(base_price * rng.choice([1.0, 0.9, 0.85, 1.05]), 2)

    return {
        "商品名": name,
        "价格": price,
        "库存": rng.choice([0, 12, 36, 88, 150, 320]),
        "规格": spec,
        "材质": material,
        "上架时间": _format_time(
            -rng.randint(30, 400), rng.randint(0, 23), rng.randint(0, 59)
        ),
    }


@tool
def query_logistics(order_id: int) -> dict:
    """按订单号查询包裹的物流进度。

    用户问「我的快递到哪了、什么时候能到、有没有签收、是哪家快递」时使用。
    例如用户说「订单 1001 的快递到哪了」，就调用本工具，把 1001 作为 order_id 传入。
    返回运单号、承运商、当前状态、最新轨迹描述和更新时间。
    注意：这里传的仍是订单号，不是运单号；运单号由订单号推导而来，可直接用于官网查询。
    """
    # 与订单用不同的种子，避免订单和物流的随机结果完全同步，看起来才像真实系统
    rng = random.Random(order_id + 100000)

    carrier, code = _CARRIERS[rng.randrange(len(_CARRIERS))]
    stage = _LOGISTICS_STAGES[rng.randrange(len(_LOGISTICS_STAGES))]
    city = _CITIES[rng.randrange(len(_CITIES))]

    traces = {
        "已揽收": f"快件已在【{city}】揽收，等待发往转运中心",
        "运输中": f"快件已到达【{city}转运中心】，正在发往下一站",
        "派送中": f"快件已到达【{city}派送点】，快递员正在派送，请保持电话畅通",
        "已签收": f"快件已签收，签收人：本人。感谢使用{carrier}",
    }

    return {
        # 运单号直接由订单号推导：前缀区分承运商，后段就是订单号本身
        "运单号": f"{code}{order_id:010d}",
        "承运商": carrier,
        "当前状态": stage,
        "最新轨迹": traces[stage],
        "更新时间": _format_time(
            rng.randint(0, 10), rng.randint(0, 23), rng.randint(0, 59)
        ),
    }
