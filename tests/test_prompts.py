from app.prompts import render_extract_instruction, render_system


def test_system_prompt_带上店铺名():
    text = render_system("测试小店")
    assert "测试小店" in text


def test_system_prompt_含关键行为约束():
    text = render_system("测试小店")
    assert "不编造" in text          # 反幻觉
    assert "转人工" in text          # 认怂兜底
    assert "追问" in text            # 信息不足先问


def test_system_prompt_要求应答回顾类问题():
    """模型原本会答「没有记录」，即使上下文就在手里。"""
    text = render_system("测试小店")
    assert "我刚才说了什么" in text
    assert "复述" in text
    assert "没有记录" in text        # 明确禁止这种说法


def test_system_prompt_模板有占位符():
    from app.prompts import SYSTEM_PROMPT

    assert "shop_name" in SYSTEM_PROMPT.input_variables


def test_extract_instruction_点名输出字段():
    text = render_extract_instruction()
    assert "order_id" in text
    assert "missing_fields" in text
    assert "不要编造" in text
