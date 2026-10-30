from enum import Enum

from pydantic import BaseModel, Field


class AfterSaleIntent(str, Enum):
    RETURN = "return"             # 退货
    EXCHANGE = "exchange"         # 换货
    REPAIR = "repair"             # 维修
    REFUND_ONLY = "refund_only"   # 仅退款
    OTHER = "other"


class AfterSaleRequest(BaseModel):
    """售后描述的固定字段表示，供 with_structured_output 使用。"""

    order_id: str | None = Field(
        default=None,
        description=(
            "订单号，只接受 SO 加 8 位数字的格式，例如 SO20261029001。"
            "位数不对或用户随口编的，必须返回 null，不要填字符串 \"null\" 也不要编造"
        ),
    )
    intent: AfterSaleIntent = Field(description="用户诉求类型")
    reason: str | None = Field(default=None, description="用户给出的原因")
    expected_solution: str | None = Field(default=None, description="用户期望的方案")
    missing_fields: list[str] = Field(
        default_factory=list,
        description=(
            "推进售后还缺哪些信息，必填不得留空。"
            "order_id 为空时必须包含「订单号」；"
            "说不清原因时包含「原因」；"
            "涉及质量问题时包含「凭证」"
        ),
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="抽取置信度")
