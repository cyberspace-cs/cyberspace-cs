"""M6/M7 审计 benchmark：对 datasets/index.jsonl 里的每个样本，跑审计 Agent，按 ground truth 判分。

用法（密钥走环境变量，绝不写入仓库）：
    $env:LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    $env:LLM_API_KEY="sk-..."
    $env:LLM_MODELS="qwen3.8-flash,deepseek-v4-flash,qwen3.8-max"
    py run_benchmark.py

M7 新增：
    py run_benchmark.py --repeat 5          # 每个 (模型,样本) 跑 5 次，输出 mean±std
    py run_benchmark.py --scorer v2         # 用 v2 打分（类型+定位IoU+严重度加权）
    py run_benchmark.py --out results.json  # 结果落盘，供难度/IRT 分析复用

为什么需要 --repeat：LLM 单次采样有随机性（README M6 已观察到"上次翻车这次满分"），
单次结果不构成结论。多次运行才能给出 mean ± std，才能谈差距是否显著。

M7+ 新增：时间与成本记账（docs/10-action-plan 第一步）
    py run_benchmark.py --solved-threshold 0.5   # F1 >= 0.5 才算"做对"

为什么必须记这两列：两个模型同样考 90 分，一个花 3 分钟 2 分钱、另一个花 1 小时
30 块钱——只看分数是平手，看完成本是天壤之别。没有这两列，这个问题答不出来。

成本口径是 **cost per solved task**（ALE-Bench 口径）：分母只算做对的题数，
分子含全部调用开销。公式：每成功一题成本 = 每题成本 ÷ 命中率。
详见 engine/llm/pricing.py。

⚠️ 单价必须配置，否则 cost 显示为 n/a（不编造价格）：
    $env:LLM_PRICES='{"qwen3.8-flash":{"in":0.2,"out":2.0}}'
"""

from __future__ import annotations

import warnings

from collections import defaultdict

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.agents import AuditAgent  # noqa: E402
from engine.llm import LLMClient, PriceTable, cost_per_solved_task, load_dotenv  # noqa: E402
from engine.llm.client import LLMTruncatedWarning  # noqa: E402
from engine.scorers.report_score import score_report, score_report_v2  # noqa: E402


def load_ground_truth(sample_dir: Path) -> list:
    meta = json.loads((sample_dir / "meta.json").read_text(encoding="utf-8"))
    return meta.get("issues", [])


def fmt_money(v):
    return "n/a" if v is None else f"${v:.4f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="审计 benchmark")
    ap.add_argument("--repeat", type=int, default=1,
                    help="每个 (模型,样本) 重复次数，默认 1；建议 >=5 以获得稳定结论")
    ap.add_argument("--scorer", default="v1", choices=["v1", "v2"],
                    help="v1=类型+函数匹配；v2=类型+定位IoU+严重度加权（默认 v1）")
    ap.add_argument("--only", default="", help="逗号分隔的 sample_id，默认全部")
    ap.add_argument("--out", default="", help="结果 JSON 落盘路径")
    ap.add_argument("--solved-threshold", type=float, default=0.5,
                    help="F1 >= 该值记为'做对'，用于 cost per solved task（默认 0.5）")
    ap.add_argument("--timeout", type=int, default=180, help="单次请求超时秒数（默认 180）")
    ap.add_argument("--strict", action="store_true",
                    help="遇到疑似截断的空答案直接报错中止，而不是记 0 分继续跑")
    args = ap.parse_args()

    # .env 加载（若环境变量已有则不被覆盖）；让密钥从文件读取，不必每次 export
    loaded = load_dotenv()
    if loaded:
        print(f"（已从 .env 加载 {loaded} 条配置）")

    base_url = os.environ["LLM_BASE_URL"]
    api_key = os.environ["LLM_API_KEY"]
    models = [m.strip() for m in os.environ.get("LLM_MODELS", "qwen3.8-flash").split(",") if m.strip()]
    strategy = os.environ.get("LLM_PROMPT", "standard")
    score_fn = score_report_v2 if args.scorer == "v2" else score_report
    prices = PriceTable.load(ROOT)

    # 截断告警默认只响一次（Python 的默认去重），跑 benchmark 时希望每题都看见：
    # 同一 nl filter 复位，保证每个模型至少报一次。
    warnings.simplefilter("always", LLMTruncatedWarning)

    ds = ROOT / "datasets"
    index = [
        json.loads(line)
        for line in (ds / "index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        index = [r for r in index if r["sample_id"] in wanted]

    print("=" * 100)
    print(f"审计 benchmark · 样本 {len(index)} 个 · 模型 {len(models)} 个 · "
          f"prompt={strategy} · scorer={args.scorer} · repeat={args.repeat}")
    if not prices.configured:
        print("⚠️  未配置单价表 —— 成本列将显示 n/a。"
              "设置 $env:LLM_PRICES='{\"模型名\":{\"in\":0.2,\"out\":2.0}}' 以启用（单位：USD/百万 token）")
    print("=" * 100)

    summary, all_runs = [], {}
    for model in models:
        client = LLMClient(base_url=base_url, api_key=api_key, model=model,
                           temperature=float(os.environ.get("LLM_TEMPERATURE", "0") or 0),
                           timeout=args.timeout,
                           max_tokens=int(os.environ.get("LLM_MAX_TOKENS", 4096)),
                           thinking=os.environ.get("LLM_THINKING") or None,
                           strict=args.strict)
        agent = AuditAgent(client, strategy=strategy)
        per_sample = {}
        m_wall = m_tin = m_tout = 0
        m_calls = 0
        m_empty = 0
        # 用「应答里实际返回的模型名」记账：有的网关会把过时的请求名静默换成别的模型
        # （实测 deepseek 官方会把 deepseek-v4-flash 换成 deepseek-flash），
        # 按请求名算钱就会算到另一个模型头上。
        buckets = defaultdict(lambda: {"tin": 0, "tout": 0})

        for s in index:
            planted = (ds / s["planted"]).read_text(encoding="utf-8")
            gt = load_ground_truth(ds / s["sample_id"])

            f1s, recs, precs, walls = [], [], [], []
            last = {"tp": 0, "fp": 0, "fn": 0}
            s_tin = s_tout = 0
            s_empty = 0
            for _ in range(max(1, args.repeat)):
                t0 = time.time()
                report = agent.audit(planted)
                wall_ms = int((time.time() - t0) * 1000)
                usage = report.get("_usage") or {}
                tin = usage.get("tokens_in", 0)
                tout = usage.get("tokens_out", 0)
                s_tin += tin
                s_tout += tout
                buckets[usage.get("model", model)]["tin"] += tin
                buckets[usage.get("model", model)]["tout"] += tout
                if usage.get("empty_text"):
                    s_empty += 1
                m_calls += 1
                walls.append(wall_ms)

                sc = score_fn(gt, report["findings"])
                last = sc
                f1s.append(sc["f1"])
                recs.append(sc["recall"])
                precs.append(sc["precision"])

            m_wall += sum(walls)
            m_tin += s_tin
            m_tout += s_tout
            m_empty += s_empty

            per_sample[s["sample_id"]] = {
                "vuln_type": s["vuln_type"],
                "f1_mean": round(statistics.fmean(f1s), 4),
                "f1_std": round(statistics.pstdev(f1s), 4) if len(f1s) > 1 else 0.0,
                "recall_mean": round(statistics.fmean(recs), 4),
                "precision_mean": round(statistics.fmean(precs), 4),
                "runs": len(f1s),
                "empty_text_runs": s_empty,
                # --- 时间与成本 ---
                "wall_ms_mean": int(statistics.fmean(walls)),
                "tokens_in": s_tin,
                "tokens_out": s_tout,
                "cost_usd": prices.estimate_cost(model, s_tin, s_tout),
            }
            empty_note = f" ⚠️空答案{s_empty}/{len(f1s)}" if s_empty else ""
            std_note = f" ±{per_sample[s['sample_id']]['f1_std']:.3f}" if len(f1s) > 1 else ""
            print(f"  [{model}] {s['sample_id']} gt={s['vuln_type']:<15} "
                  f"tp={last['tp']} fp={last['fp']} fn={last['fn']} "
                  f"R={last['recall']:.3f} P={last['precision']:.3f} "
                  f"F1={per_sample[s['sample_id']]['f1_mean']:.3f}{std_note} "
                  f"{per_sample[s['sample_id']]['wall_ms_mean']}ms{empty_note}")

        # 全样本汇总（按样本平均，避免长样本主导）
        if per_sample:
            m_f1 = statistics.fmean(v["f1_mean"] for v in per_sample.values())
            m_r = statistics.fmean(v["recall_mean"] for v in per_sample.values())
            m_p = statistics.fmean(v["precision_mean"] for v in per_sample.values())
            m_std = statistics.fmean(v["f1_std"] for v in per_sample.values())
        else:
            m_f1 = m_r = m_p = m_std = 0.0

        # --- 成本：ALE-Bench 口径 ---
        # 按实际应答模型名分别计价再求和；任一个模型没配单价，总成本就显示 n/a
        n_solved = sum(1 for v in per_sample.values() if v["f1_mean"] >= args.solved_threshold)
        costs = [prices.estimate_cost(name, b["tin"], b["tout"]) for name, b in buckets.items()]
        if costs and all(c is not None for c in costs):
            total_cost = round(sum(costs), 6)
        elif buckets:
            # 有一部分模型没单价：宁可显示 n/a，也不拿"已知的部分"冒充总成本
            missing = [name for name, b in buckets.items()
                       if prices.estimate_cost(name, b["tin"], b["tout"]) is None]
            total_cost = None
            print(f"⚠️  [{model}] 以下模型缺少单价，成本记 n/a：{', '.join(missing)}")
        else:
            total_cost = prices.estimate_cost(model, m_tin, m_tout)
        cps = cost_per_solved_task(total_cost, n_solved)

        summary.append({
            "model": model, "recall": m_r, "precision": m_p, "f1": m_f1, "f1_std": m_std,
            "wall_ms": m_wall, "calls": m_calls,
            "tokens_in": m_tin, "tokens_out": m_tout,
            "cost_usd": total_cost, "solved": n_solved, "n_tasks": len(per_sample),
            "cost_per_solved_usd": cps,
            "empty_text_calls": m_empty, "truncated_calls": client.truncated_calls,
            "served_by": sorted(buckets.keys()),
        })
        all_runs[model] = per_sample

    # ---------------------------------------------------------------- 分数榜
    print("\n" + "=" * 100)
    print(f"{'model':<20} {'Recall':>7} {'Prec':>7} {'F1':>7} {'F1 std':>8} "
          f"{'Wall(s)':>8} {'Tokens':>9} {'Cost':>9} {'Solved':>7} {'$/solved':>10} {'空答':>5}")
    print("-" * 108)
    for r in summary:
        print(f"{r['model']:<20} {r['recall']:>7.3f} {r['precision']:>7.3f} "
              f"{r['f1']:>7.3f} {r['f1_std']:>8.3f} "
              f"{r['wall_ms']/1000:>8.1f} {r['tokens_in']+r['tokens_out']:>9} "
              f"{fmt_money(r['cost_usd']):>9} {str(r['solved'])+'/'+str(r['n_tasks']):>7} "
              f"{fmt_money(r['cost_per_solved_usd']):>10} {r['empty_text_calls']:>5}")
    print("=" * 108)
    for r in summary:
        served = [m for m in r["served_by"] if m != r["model"]]
        if served:
            print(f"ℹ️  {r['model']} 的请求被网关换成 {', '.join(served)}；成本按后者单价计算")

    if args.repeat == 1:
        print("提示：当前为单次采样，结论不稳定。建议加 --repeat 5 再对比模型。")
    if any(r["tokens_in"] + r["tokens_out"] == 0 for r in summary):
        print("⚠️  token 数全为 0：说明 LLM 网关没有返回 usage，成本无从计算。"
              "请确认网关是否支持该字段（部分代理会剥掉 usage）。")
    if any(r["empty_text_calls"] for r in summary):
        print("⚠️  存在空答案调用：其中一部分不是'模型认为没漏洞'，而是回答被 token 上限截断。"
              "空答案会让 recall 悄悄变成 0，必须先看 Engine emitted 的截断告警再解读分数。")
    if any(r["truncated_calls"] for r in summary):
        print("⚠️  有调用被 token 上限截断：提高 LLM_MAX_TOKENS 或 LLM_THINKING=off 后重跑。")
    if not prices.configured:
        print("⚠️  成本列为 n/a：未配置 LLM_PRICES。这不代表免费 —— 是'不知道'。")

    if args.out:
        payload = {
            "scorer": args.scorer,
            "repeat": args.repeat,
            "solved_threshold": args.solved_threshold,
            "prices_configured": prices.configured,
            "summary": summary,
            "results": all_runs,
        }
        out_path = ROOT / args.out
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
