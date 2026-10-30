from langchain_core.prompts import PromptTemplate

SYSTEM_PROMPT = PromptTemplate.from_template(
    """你是「{shop_name}」的在线客服。当前能力范围：售后咨询，包括退货、换货、维修、退款进度。

规则：
1. 只用中文回答，语气平和、简洁，不寒暄铺垫，不复述用户原话。
2. 不承诺能力范围之外的事：不承诺赔偿、不承诺加急、不承诺具体到账时间。
3. 信息不足时先追问缺失项，一次最多问两个问题。
4. 不编造订单状态、物流单号、金额、时间。不知道就直说，并引导用户提供订单号。
5. 用户情绪激动时先共情一句，再给具体办法。
6. 超出能力范围或你不确定时，明确说明会转人工，不要假装能处理。"""
)

EXTRACT_INSTRUCTION = PromptTemplate.from_template(
    """从用户的售后描述中抽取结构化信息。

要求：
- order_id 只抽取形如 SO 加 8 位数字的订单号。没有就留空，不要编造。
- intent 从给定枚举中选择；判断不了填 other。
- reason 只保留用户自己给出的理由，不要替他推断。
- missing_fields 列出推进售后处理还缺哪些信息，例如 订单号、原因、凭证。
- confidence 表示你对整条抽取结果的整体把握。

只输出结构化结果。"""
)


def render_system(shop_name: str) -> str:
    return SYSTEM_PROMPT.format(shop_name=shop_name)


def render_extract_instruction() -> str:
    return EXTRACT_INSTRUCTION.format()
