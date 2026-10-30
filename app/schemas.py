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
        default=None, description="订单号，形如 SO20261029001。没有就留空，不要编造"
    )
    intent: AfterSaleIntent = Field(description="用户诉求类型")
    reason: str | None = Field(default=None, description="用户给出的原因")
    expected_solution: str | None = Field(default=None, description="用户期望的方案")
    missing_fields: list[str] = Field(
        default_factory=list, description="推进售后还缺哪些信息，例如 订单号、原因、凭证"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="抽取置信度")
