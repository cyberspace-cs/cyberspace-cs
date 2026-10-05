"""S1 实测入口：拿真实 DeepSeek judge 测审计题上的真FNR / FPR。

跑法（密钥走 .env，绝不入库）：
    python run_s1_judge_probe.py --model deepseek-flash --seeds 60 --workers 8
    python run_s1_judge_probe.py --model deepseek-v4-pro --seeds 40 --workers 6

⚠️ 本机有 http_proxy 等环境变量，会挡住对 api.deepseek.com 的直连。
   真跑 LLM 必须先清代理，否则全部网络失败（与 git push 同一个坑）。
   脚本自己会清，并在输出里报告是否真的连上了。

这是 **go/no-go 闸门**，判据在跑之前就写死在 vts/judge_probe.py 顶部：
    FNR*(最宽松 arm C 的端到端漏判率) >= 0.20 → 继续；< 0.20 → 转向。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.llm import load_dotenv                     # noqa: E402
from vts.audit_core import FRAUD_OPS                   # noqa: E402
from vts.judge_probe import (ARMS, ARM_DESC, Cell, collapse,  # noqa: E402
                             reason_contradiction, run_arm, score, verdict)

# 代理会静默吃掉对 DeepSeek 的直连（git push 踩过同一个坑）
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--seeds", type=int, default=60)
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--repeat", type=int, default=1,
                    help="每个样本重复调用次数（>=2 时多数票汇总）。实测该网关 temperature=0 并不确定，单次调用不足以支撑 go/no-go。")
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--conditions", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--jsonl", default="")
    ap.add_argument("--threshold", type=float, default=0.20)
    args = ap.parse_args()

    load_dotenv(ROOT)

    conds = ([c for c in args.conditions.split(",") if c]
             or (sorted(FRAUD_OPS) + ["clean"]))
    bad = [c for c in conds if c != "clean" and c not in FRAUD_OPS]
    if bad:
        print(f"未知条件：{bad}；可选={sorted(FRAUD_OPS)}+clean")
        return 2

    tag = args.out or f"results_s1_judge_{args.model}"
    out_json = ROOT / (tag if tag.endswith(".json") else tag + ".json")
    jsonl = Path(args.jsonl) if args.jsonl else ROOT / (
        (tag.replace(".json", "") or "results_s1_judge") + "_raw.jsonl")

    from engine.llm.client import LLMClient
    from engine.llm.pricing import PriceTable

    prices = PriceTable.load(ROOT)

    def factory() -> LLMClient:
        # strict=False：空答案要能落盘成"基础设施故障"而不是中断整批
        #
        # ⚠️ thinking 默认必须**关掉**，这不是可选项，是实测踩出来的：
        # deepseek-flash 在 thinking 模式下会把 8192 token **全部烧在思考链上**
        # （finish_reason=length，输出 8195/8192，reasoning=8195），
        # content 返回**空字符串**，而 HTTP 是 200、usage 完整 —— 从外面看一切正常。
        # 试点实测：5 个样本 4 个空答案，只剩 1 个可用，于是 score() 报出
        # "FNR=0.000、NO-GO"。**那是假结论**：不是 judge 看得准，
        # 而是它几乎没答。空样本被剔除出分母后，分母只剩 1，谁都能"全对"。
        #
        # 这类失败比报错危险得多，因为它伪装成结论。所以：
        #   1. thinking=off，让token 花在答案上而不是思考链
        #   2. 空答案率过高时直接判"数据不可用"并拒绝出结论（见下方守卫）
        return LLMClient(model=args.model, temperature=0.0,
                         max_tokens=args.max_tokens, thinking="off",
                         strict=False, timeout=180)

    def price_of(model: str, tin: int, tout: int) -> float:
        c = prices.estimate_cost(model, tin, tout)
        return float(c) if c is not None else 0.0

    print("=" * 74)
    print(f"S1 真实 judge 可靠性实测  model={args.model}  seeds={args.seeds}")
    print(f"条件：{', '.join(conds)}")
    print(f"arm：{', '.join(ARMS)}   每 arm {len(conds)}x{args.seeds} 次调用")
    print("=" * 74)

    # 连通性预检：不通就别开跑，否则几千次调用全是网络错误
    probe = factory()
    try:
        r = probe.chat_detailed(
            [{"role": "user", "content": '只回复 {"ok":true}'}],
            max_tokens=2048)
        if r.empty_text:
            print(f"[致命] 连通性预检返回空答案（model={r.model}）。"
                  "多为 thinking 烧光预算：--max-tokens 再调大或 thinking=off。")
            return 3
        print(f"[连通] {r.model}  {r.latency_ms}ms  "
              f"in={r.usage.tokens_in}/out={r.usage.tokens_out}")
    except Exception as exc:
        print(f"[致命] 连不通 {args.model}: {type(exc).__name__}: {exc}")
        print("      若是网络错误，试试清代理：unset http_proxy https_proxy "
              "HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY")
        return 3

    all_cells: list[Cell] = []
    for arm in [a for a in ARMS if a in args.arms]:
        print(f"\n--- arm {arm}: {ARM_DESC[arm]} ---")
        cells = run_arm(arm, conds, args.seeds, factory, price_of,
                        jsonl, workers=args.workers,
                        max_tokens=args.max_tokens, repeat=args.repeat)
        # run_arm 每次都把整个 JSONL 读回来；必须**按本次 arm 过滤**，
        # 否则第2/3 个 arm 的样本会被重复累加（曾出现 1000/600/200 的假样本数）
        all_cells.extend([c for c in cells if c.arm == arm])
        merged, n_dis = collapse(all_cells)
        s = score([c for c in merged if c.arm == arm])
        if arm in s:
            a = s[arm]
            print(f"  可用样本 {a['n_usable']}（注入 {a['n_injected']}"
                  f" + 干净 {a['n_clean']}）  空答案 {a['n_empty']}  "
                  f"不可解析 {a['n_unparsed']}")
            print(f"  检测层FNR={a['det_fnr']:.3f}  归因层FNR={a['attr_fnr']:.3f}  "
                  f"端到端FNR={a['e2e_fnr']:.3f}  FPR={a['fpr']:.3f}")
            print(f"  重复调用分歧率={a['disagree_rate']:.3f}"
                  f"（{n_dis} 条不一致）")

    merged, n_dis = collapse(all_cells)
    res = score(merged)
    cost = sum(c.cost for c in all_cells)
    tok_in = sum(c.tokens_in for c in all_cells)
    tok_out = sum(c.tokens_out for c in all_cells)

    contra = reason_contradiction(all_cells)
    report = {
        "model": args.model,
        "reason_contradiction": contra,
        "seeds": args.seeds,
        "conditions": conds,
        "repeat": args.repeat,
        "arms": res,
        "usage": {"calls": len(all_cells), "tokens_in": tok_in,
                  "tokens_out": tok_out, "cost_usd": round(cost, 4),
                  "cost_per_call": round(cost / max(1, len(all_cells)), 6)},
        "decision_rule": ("FNR*(最宽松 arm C 端到端 FNR) >= 0.20 继续，否则转向。"
                          "取最宽松配置是对自己不利的选择。"),
    }
    report["decision"] = verdict(res, args.threshold)

    print("\n" + "=" * 74)
    print(f"{'arm':<32}{'注入':>5}{'干净':>5}{'检测FNR':>9}{'归因FNR':>9}"
          f"{'端到端FNR':>11}{'FPR':>8}{'分歧率':>8}")
    for arm in ARMS:
        if arm not in res:
            continue
        a = res[arm]
        print(f"{ARM_DESC[arm][:30]:<32}{a['n_injected']:>5}{a['n_clean']:>5}"
              f"{a['det_fnr']:>9.3f}{a['attr_fnr']:>9.3f}{a['e2e_fnr']:>11.3f}"
              f"{a['fpr']:>8.3f}{a['disagree_rate']:>8.3f}")

    print("\n" + "=" * 74)
    print("结论与理由自相矛盾（flag=true，但 reason 里写着\"正常/无异常/一致\"）")
    for arm in ARMS:
        d = contra.get(arm)
        if not d or not d["n_flagged"]:
            continue
        print(f"   arm {arm}: {d['contradiction']}/{d['n_flagged']}"
              f" = {d['rate']:.1%}的\"报警\"被它自己的理由否定")

    if "C" in res:
        print(f"\n--- 逐手法端到端 FNR（arm C，最宽松）---")
        print(f"{'手法':<16}{'n':>5}{'e2eFNR':>9}{'检测FNR':>9}   95%CI")
        for op, d in sorted(res["C"]["per_op"].items()):
            lo, hi = d["ci95"]
            print(f"{op:<16}{d['n']:>5}{d['e2e_fnr']:>9.3f}"
                  f"{d['det_fnr']:>9.3f}   [{lo:.3f}, {hi:.3f}]")
        print(f"\n   arm C 报出的手法分布（查退化解：只会报一种=不可信）："
              f"{res['C']['kind_dist']}")

    d = report["decision"]
    print("\n" + "=" * 74)
    print("GO / NO-GO 判定")
    if d["decision"].startswith("INCOMPLETE"):
        print(f"  → {d['decision']}")
        print(f"  原因：{d.get('why')}")
        print(f"  {d.get('hint', '')}")
    else:
        print(f"  规则：{d.get('rule')}")
        print(f"  FNR* = {d.get('FNR_star')}  95%CI={d.get('FNR_star_ci95')}")
        print(f"  可用注入样本 = {d.get('n_usable_injected')}")
        print(f"  区间是否与阈值 {args.threshold} 分离："
              f"{d.get('ci_excludes_threshold')}")
        print(f"  → {d['decision']}")
        if d["decision"].startswith("NO-GO"):
            print("\n  按预先写死的规则，应转向。执行前请确认三件事：")
            print("   1. FNR 的 95%CI 上界确实低于阈值（样本量够不够）")
            print("   2. 空答案/不可解析率没有高到吞掉分母")
            print("   3. arm C 手法分布不是退化解（不是只报一种类型）")
    print("=" * 74)
    print(f"用量：{report['usage']['calls']} 次调用  "
          f"in={tok_in}  out={tok_out}  约 ${cost:.4f}")

    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"已写出 {out_json.name}")
    print(f"原始逐条响应 {jsonl.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
