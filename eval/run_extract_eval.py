"""结构化抽取评估：用标注样例跑真实上游，算字段级准确率。

用法：
    python eval/run_extract_eval.py
    python eval/run_extract_eval.py --limit 5      # 只跑前 5 条，省钱/调通
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.memory import SessionStore  # noqa: E402
from app.service import ChatService  # noqa: E402

CASES = ROOT / "eval" / "extract_cases.jsonl"
OUT = ROOT / "eval" / "results.json"


def load_cases(limit: int | None = None):
    cases = []
    with CASES.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases[:limit] if limit else cases


def missing_hit(got_fields: list[str], needle: str) -> bool:
    joined = " ".join(got_fields)
    return needle in joined


async def main(limit: int | None, delay: float) -> int:
    settings = get_settings()
    service = ChatService(model=get_llm(), store=SessionStore(), settings=settings)

    cases = load_cases(limit)
    rows = []

    for i, case in enumerate(cases, 1):
        text = case["text"]
        expect = case["expect"]
        try:
            got = await service.extract(text)
            got_dict = got.model_dump()
            got_dict["intent"] = got.intent.value
        except Exception as exc:  # 单条失败不中断整轮
            rows.append({"text": text, "expect": expect, "error": str(exc)})
            print(f"[{i}/{len(cases)}] ✗ 调用失败: {exc}")
            continue

        rows.append({"text": text, "expect": expect, "got": got_dict})
        print(f"[{i}/{len(cases)}] {got_dict['intent']:<12} {got_dict['order_id'] or '-':<16} {text[:24]}")
        if delay:
            await asyncio.sleep(delay)

    ok_cases = [r for r in rows if "got" in r]

    # 订单号：None 对 None 也算对
    order_total = len(ok_cases)
    order_right = sum(
        1 for r in ok_cases if r["got"]["order_id"] == r["expect"]["order_id"]
    )

    # 意图
    intent_right = sum(
        1 for r in ok_cases if r["got"]["intent"] == r["expect"]["intent"]
    )

    # 缺失项召回：只统计标注了 must_miss 的样本
    miss_cases = [r for r in ok_cases if r["expect"]["must_miss"]]
    miss_right = sum(
        1
        for r in miss_cases
        if all(missing_hit(r["got"]["missing_fields"], n) for n in r["expect"]["must_miss"])
    )

    def rate(a, b):
        return f"{a}/{b} = {a / b * 100:.1f}%" if b else "n/a"

    print("\n" + "=" * 46)
    print(f"样本数        : {len(cases)}（成功 {len(ok_cases)} 条）")
    print(f"订单号准确率  : {rate(order_right, order_total)}")
    print(f"意图准确率    : {rate(intent_right, order_total)}")
    print(f"缺失项召回率  : {rate(miss_right, len(miss_cases))}")
    print("=" * 46)

    fails = []
    for r in ok_cases:
        if r["got"]["order_id"] != r["expect"]["order_id"]:
            fails.append(f"  订单号 期望={r['expect']['order_id']} 实际={r['got']['order_id']} | {r['text'][:30]}")
        if r["got"]["intent"] != r["expect"]["intent"]:
            fails.append(f"  意图   期望={r['expect']['intent']} 实际={r['got']['intent']} | {r['text'][:30]}")
    for r in miss_cases:
        for n in r["expect"]["must_miss"]:
            if not missing_hit(r["got"]["missing_fields"], n):
                fails.append(f"  缺失项 期望含「{n}」实际={r['got']['missing_fields']} | {r['text'][:30]}")

    if fails:
        print("\n失败明细：")
        print("\n".join(fails))

    OUT.write_text(
        json.dumps({"rows": rows, "summary": {
            "total": len(cases), "ok": len(ok_cases),
            "order_right": order_right, "intent_right": intent_right,
            "miss_right": miss_right, "miss_total": len(miss_cases),
        }}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n明细已写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--delay", type=float, default=0.5, help="每条之间间隔秒数，避免免费档限流")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.limit, a.delay)))
