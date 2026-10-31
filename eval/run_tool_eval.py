"""工具调用标注样例评估。

Prompt 与工具描述属于「不可单测」的产物，按项目约定用标注样例验证，
替代 TDD 的红绿循环。

每条样例断言三件事：
1. 选中了期望的工具（或明确期望「一个都不调」）
2. 回答里出现了工具真实返回的关键内容
3. 回答里没有出现不该出现的编造内容

用法：
    .venv/Scripts/python.exe eval/run_tool_eval.py [--delay 2]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.llm import get_llm  # noqa: E402
from app.db.base import build_engine, build_sessionmaker  # noqa: E402
from app.memory import SessionStore  # noqa: E402
from app.service import ChatService  # noqa: E402
from app.tools.business import query_order, query_logistics, query_product  # noqa: E402
from app.tools.faq import make_query_faq  # noqa: E402
from app.tools.registry import ToolRegistry  # noqa: E402
from app.tools.ticket import make_create_ticket  # noqa: E402

# (说明, 用户输入, 期望工具名或 None, 回答必须包含任一, 回答必须不含任一)
CASES = [
    ("查物流", "订单 1001 的物流到哪了", "query_logistics",
     ["签收", "派送", "运输", "揽收"], []),
    ("查订单", "订单 1001 里买的是什么", "query_order",
     ["衬衫", "裤", "开衫", "T恤", "冲锋衣", "西裤"], []),
    ("查FAQ命中", "退货政策是什么", "query_faq",
     ["7 天", "7天", "七天"], []),
    ("FAQ漏召回", "邮费是多少", "query_faq",
     ["人工", "查不到", "无法", "不确定"], ["满 99", "满99", "包邮"]),
    ("闲聊不查工具", "你好", None, [], []),
    ("能力边界", "你们老板是谁", None,
     ["人工", "无法", "不清楚", "不知道", "不了解"], []),
]


async def run_case(service: ChatService, idx: int, case, delay: float) -> bool:
    label, user_input, want_tool, must_have, must_not = case
    toks: list[str] = []
    tool_names: list[str] = []

    async for ev in service.stream_with_tools(f"eval-{idx}", user_input):
        if ev["event"] == "token":
            toks.append(ev["data"]["delta"])
        elif ev["event"] == "tool":
            if ev["data"]["status"] == "running":
                tool_names.append(ev["data"]["name"])

    answer = "".join(toks)
    picked = tool_names[0] if tool_names else None

    problems = []
    if want_tool is None:
        if tool_names:
            problems.append(f"不该调工具，实际调了 {tool_names}")
    elif picked != want_tool:
        problems.append(f"期望调 {want_tool}，实际调 {picked or '无'}")

    if must_have and not any(k in answer for k in must_have):
        problems.append(f"回答缺关键词 {must_have}")

    hit = [k for k in must_not if k in answer]
    if hit:
        problems.append(f"回答含编造内容 {hit}")

    mark = "✅" if not problems else "❌"
    print(f"{mark} [{idx}] {label:<12} 工具={picked or '无':<16} 回答={answer[:60]}")
    for p in problems:
        print(f"      ↳ {p}")

    await asyncio.sleep(delay)
    return not problems


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=2.0, help="每条之间的间隔秒数")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    args = ap.parse_args()

    settings = get_settings()
    engine = build_engine(settings.database_url)
    maker = build_sessionmaker(engine)

    cases = CASES[: args.limit] if args.limit else CASES
    passed = 0

    async with maker() as session:
        registry = ToolRegistry()
        for t in (query_order, query_product, query_logistics):
            registry.register(t)
        registry.register(make_query_faq(session))
        registry.register(make_create_ticket(session, 1))

        model = get_llm()
        service = ChatService(
            model=model,
            store=SessionStore(),
            settings=settings,
            registry=registry,
        )

        for idx, case in enumerate(cases, start=1):
            try:
                if await run_case(service, idx, case, args.delay):
                    passed += 1
            except Exception as exc:  # 单条失败不中断整轮
                print(f"❌ [{idx}] {case[0]:<12} 异常: {type(exc).__name__}: {exc}")

    await engine.dispose()
    print(f"\n通过 {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
