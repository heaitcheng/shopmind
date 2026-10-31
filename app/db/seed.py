"""FAQ 种子数据。

可重复执行：每次先清空四张表再灌入同一份数据，结果完全一致。

注意：运费相关内容一律写作「运费」，整个 faq 表中不出现「邮费」二字。
这是刻意留的漏召回样本——「邮费是多少」查不出来，用于对比后续向量检索的效果。

模块导入时不做任何连接动作，`python -m app.db.seed` 才真正执行。
"""

import asyncio
from typing import Final

from sqlalchemy import text

from app.core.config import get_settings
from app.db.base import build_engine, build_sessionmaker, create_all
from app.db.models import Conversation, Faq, Message

# (question, answer, category)
FAQ_SEED: Final[tuple[tuple[str, str, str], ...]] = (
    # ---- 售后：退货 / 换货 / 维修 ----
    (
        "退货政策是什么？",
        "自签收之日起 7 天内，商品未拆封且不影响二次销售即可申请无理由退货，"
        "生鲜与定制类商品除外。商品有质量问题时退货运费由本店承担，"
        "非质量问题的退货运费由买家承担。",
        "售后",
    ),
    (
        "怎么申请退货？",
        "进入「我的订单」找到对应订单，点击「申请售后」→ 选择退货退款 → "
        "填写原因并上传凭证，提交后 1 个工作日内审核。审核通过后按页面提示寄回商品。",
        "售后",
    ),
    (
        "换货怎么操作？",
        "在订单详情页点击「申请售后」→ 选择换货，并注明需要的尺码或型号。"
        "收到寄回商品并验收合格后 48 小时内重新发出，换货运费由本店承担。",
        "售后",
    ),
    (
        "商品坏了可以维修吗？",
        "保修期内非人为损坏可免费维修：在「申请售后」中选择维修并上传故障照片，"
        "审核通过后寄回，维修周期一般为 7-15 个工作日。人为损坏只收取配件成本费。",
        "售后",
    ),
    (
        "退货运费谁承担？",
        "商品质量问题、错发漏发由本店承担退货运费；七天无理由退货由买家承担退货运费。"
        "若订单已购买运费险，可按保单约定获得赔付。",
        "售后",
    ),
    # ---- 物流 ----
    (
        "下单后多久发货？",
        "现货商品在付款后 48 小时内发出，预售商品按商品页标注时间发出。"
        "节假日顺延，发货后可在订单详情查看运单号。",
        "物流",
    ),
    (
        "运单号在哪里查看？",
        "订单状态变为「已发货」后，进入订单详情页点击「查看物流」，"
        "即可看到运单号与实时轨迹。",
        "物流",
    ),
    (
        "偏远地区运费怎么算？",
        "普通地区满 99 元包运费；新疆、西藏、内蒙古等偏远地区按重量计费，"
        "首重 1kg 收取 15 元，续重每公斤 8 元，下单时结算页会明确显示。",
        "物流",
    ),
    (
        "可以指定送达时间吗？",
        "下单时可在备注中填写期望送达时段，我们会转达给承运方，"
        "但实际送达时间以物流公司派送为准。",
        "物流",
    ),
    # ---- 支付 ----
    (
        "支持哪些支付方式？",
        "支持微信支付、支付宝、银联在线以及主流银行卡。"
        "企业客户可申请对公转账，转账后请把回单发给客服核销。",
        "支付",
    ),
    (
        "支付失败怎么办？",
        "先确认银行卡余额与单笔限额，再尝试更换支付方式。"
        "若已扣款但订单未生成，通常 1-3 个工作日内自动退回，"
        "也可联系客服提供交易流水号加急处理。",
        "支付",
    ),
    (
        "可以货到付款吗？",
        "目前仅部分地区支持货到付款，下单结算页若显示该选项即可选择，"
        "未显示则表示当前收货地址不支持。",
        "支付",
    ),
    # ---- 账户 ----
    (
        "忘记密码怎么办？",
        "在登录页点击「忘记密码」，输入注册手机号获取验证码后重置。"
        "连续 5 次输错验证码需等待 10 分钟再试。",
        "账户",
    ),
    (
        "怎么修改绑定的手机号？",
        "登录后进入「账户设置 - 安全中心 - 更换手机号」，通过原手机号验证后绑定新号码。"
        "原号码已停用请提交实名信息，由客服人工处理。",
        "账户",
    ),
    (
        "账户被冻结了怎么办？",
        "账户因异常登录或违规操作可能被临时冻结。请携带注册手机号联系在线客服，"
        "核实身份后一般 24 小时内解冻。",
        "账户",
    ),
    # ---- 发票 ----
    (
        "怎么申请发票？",
        "订单完成后在「我的订单 - 申请发票」填写抬头与税号，"
        "电子发票会在 3 个工作日内发送到预留邮箱，纸质发票随下一次发货寄出。",
        "发票",
    ),
    (
        "可以开增值税专用发票吗？",
        "可以。企业用户需提供营业执照、一般纳税人资格证明和开票信息，"
        "审核通过后由财务在 5 个工作日内开具增值税专用发票。",
        "发票",
    ),
)

# 示例会话，仅供人工查看；不灌 tickets。
CONVERSATION_SEED: Final[tuple[dict, ...]] = (
    {
        "user_id": "anon-demo-1",
        "status": "已结束",
        "messages": [
            {"role": "user", "content": "退货政策是什么？"},
            {
                "role": "assistant",
                "content": "自签收之日起 7 天内，商品未拆封且不影响二次销售即可申请无理由退货。",
            },
        ],
    },
    {
        "user_id": "anon-demo-2",
        "status": "已转人工",
        "messages": [
            {"role": "user", "content": "退货运费谁承担？"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_demo_1",
                        "name": "query_faq",
                        "arguments": {"keyword": "退货运费"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": '{"命中数": 1, "条目": [{"问题": "退货运费谁承担？"}]}',
                "tool_call_id": "call_demo_1",
            },
            {
                "role": "assistant",
                "content": "质量问题由本店承担退货运费，七天无理由退货由买家承担。",
            },
        ],
    },
)

# 按外键依赖倒序清空
_TRUNCATE_ORDER: Final[tuple[str, ...]] = ("messages", "tickets", "conversations", "faq")


async def _truncate_all(engine) -> None:
    """清空四张表。

    用 TRUNCATE 而不是 DELETE，是为了让自增 id 也回到起点，
    这样重复执行 seed 得到的结果（含主键）完全一致。
    MySQL 不允许 TRUNCATE 被外键引用的父表，故临时关闭外键检查。
    """
    autocommit = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit.connect() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for table in _TRUNCATE_ORDER:
                await conn.execute(text(f"TRUNCATE TABLE {table}"))
        finally:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


async def seed(engine) -> None:
    """建表 → 清空 → 灌入固定种子数据。可重复执行。"""
    await create_all(engine)
    await _truncate_all(engine)

    sessionmaker = build_sessionmaker(engine)
    async with sessionmaker() as session:
        async with session.begin():
            session.add_all(
                Faq(question=q, answer=a, category=c) for q, a, c in FAQ_SEED
            )
            for item in CONVERSATION_SEED:
                conv = Conversation(
                    user_id=item["user_id"],
                    status=item["status"],
                )
                session.add(conv)
                await session.flush()  # 拿到自增 id 供 messages 使用
                session.add_all(
                    Message(
                        conversation_id=conv.id,
                        role=msg["role"],
                        content=msg.get("content"),
                        tool_calls=msg.get("tool_calls"),
                        tool_call_id=msg.get("tool_call_id"),
                    )
                    for msg in item["messages"]
                )


async def main() -> None:
    engine = build_engine(get_settings().database_url)
    try:
        await seed(engine)
        async with engine.connect() as conn:
            faq_count = (await conn.execute(text("SELECT COUNT(*) FROM faq"))).scalar()
            msg_count = (await conn.execute(text("SELECT COUNT(*) FROM messages"))).scalar()
        print(f"seed 完成：faq {faq_count} 条，messages {msg_count} 条")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
