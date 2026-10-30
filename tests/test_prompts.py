from app.prompts import render_extract_instruction, render_system


def test_system_prompt_带上店铺名():
    text = render_system("测试小店")
    assert "测试小店" in text


def test_system_prompt_含关键行为约束():
    text = render_system("测试小店")
    assert "不编造" in text          # 反幻觉
    assert "转人工" in text          # 认怂兜底
    assert "追问" in text            # 信息不足先问


def test_system_prompt_模板有占位符():
    from app.prompts import SYSTEM_PROMPT

    assert "shop_name" in SYSTEM_PROMPT.input_variables


def test_extract_instruction_点名输出字段():
    text = render_extract_instruction()
    assert "order_id" in text
    assert "missing_fields" in text
    assert "不要编造" in text
