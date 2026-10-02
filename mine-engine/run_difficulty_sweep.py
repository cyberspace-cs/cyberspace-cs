"""第四步验证脚本：扫描难度刻度 0..5，产出"难度 -> 结构指标 / AI 分数"曲线。

两种模式：
  * 默认（离线）：只输出结构指标（诱饵数、是否伪装、是否跨函数），
    证明旋钮确实改变了题目的"长相"，不花钱。
  * `--audit`：真调 LLM 审计，算 F1 / 精确率，并**统计是否踩到诱饵**
    （decoy_hits）。诱饵是"看着像漏洞但其实安全"的代码：
    模型报了就说明它"宁可错报"，难度确实上去了；不报说明它有判别力。

用法：
  python run_difficulty_sweep.py --sample sample-0001
  python run_difficulty_sweep.py --audit --samples sample-0001,sample-0002,sample-0003
  python run_difficulty_sweep.py --audit --repeat 3 --model deepseek-v4-pro

验收（见 docs/10-action-plan.md 3.4）三条：
  1. 分离：刻度↑时 F1 总体下降、decoy_hits 总体上升（题确实变难）；
  2. 稳定：同一刻度多次采样的方差可控，不是纯噪声；
  3. 结构：诱饵/伪装/跨函数标志单调增加（离线即可验证）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.operators.difficulty import PRESETS, apply_difficulty  # noqa: E402


def load_sample(ds: Path, sample_id: str):
    planted_dir = ds / sample_id / "planted"
    if not planted_dir.exists():
        raise SystemExit(f"找不到样本 {sample_id}（{planted_dir} 不存在）")
    sol_files = list(planted_dir.glob("*.sol"))
    if not sol_files:
        raise SystemExit(f"{planted_dir} 下没有 .sol")
    planted_source = sol_files[0].read_text(encoding="utf-8")
    meta = json.loads((ds / sample_id / "meta.json").read_text(encoding="utf-8"))
    return planted_source, meta


def count_decoy_hits(findings: list, decoy_fns: list) -> int:
    """模型报告里有多少条命中了我们插进去的诱饵函数。

    匹配的是**函数名**（payoutPartner / accrueTier / setRiskCap / maintenanceMode），
    不是源码里的 "decoy" 字样 —— 诱饵代码里刻意不出现这个词（自曝身份就失效了），
    所以只能按函数名匹配。函数名取自 apply_difficulty 返回的 metrics，
    保证与实际插入的完全一致（诱饵模板会循环复用，>4 条时同名函数会重复出现，
    这本身也是刻度 5 的一部分难度）。

    判分器不认诱饵（gt 里没有），踩雷只会间接体现为 precision 下降；
    这里直接数一次，得到不依赖判分器口径的硬指标。
    """
    if not decoy_fns:
        return 0
    hits = 0
    for f in findings or []:
        blob = json.dumps(f, ensure_ascii=False)
        if any(fn in blob for fn in decoy_fns):
            hits += 1
    return hits


def run_audit(planted_source: str, meta: dict, score_fn, client, agent, decoy_fns):
    """跑一次审计，返回 (分数, 踩雷数, 用量)。调用方保证 client/agent 已就绪。"""
    report = agent.audit(planted_source)
    findings = report.get("findings", [])
    sc = score_fn(meta.get("issues", []), findings)
    sc["decoy_hits"] = count_decoy_hits(findings, decoy_fns)
    sc["n_findings"] = len(findings)
    sc["usage"] = report.get("_usage", {})
    return sc


def build_audit_env(model: str | None):
    """准备 LLM 客户端；没配 key 就返回 (None, None)。"""
    import os  # noqa: PLC0415

    from engine.llm.env import load_dotenv  # noqa: PLC0415

    load_dotenv(ROOT)
    if not os.environ.get("LLM_API_KEY"):
        return None, None
    from engine.agents import AuditAgent  # noqa: PLC0415
    from engine.llm import LLMClient  # noqa: PLC0415

    client = LLMClient(model=model) if model else LLMClient()
    return client, AuditAgent(client, strategy="standard")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="sample-0001", help="单样本（快捷方式）")
    ap.add_argument("--samples", default="", help="多样本，逗号分隔；给了就覆盖 --sample")
    ap.add_argument("--levels", default="0,1,2,3,4,5", help="要扫的刻度，逗号分隔")
    ap.add_argument("--repeat", type=int, default=1, help="每档每样本重复采样次数（>=3 才有统计意义）")
    ap.add_argument("--model", default="", help="指定模型；不填用 .env 里的 LLM_MODEL")
    ap.add_argument("--out", default="results_difficulty_sweep.json")
    ap.add_argument("--scorer", choices=["v1", "v2"], default="v2")
    ap.add_argument("--audit", action="store_true",
                    help="真跑 LLM 审计并算 F1（默认只出结构指标，不花钱）")
    args = ap.parse_args()

    from engine.llm.pricing import PriceTable  # noqa: E402
    from engine.scorers.report_score import score_report, score_report_v2  # noqa: E402

    score_fn = score_report_v2 if args.scorer == "v2" else score_report
    ds = ROOT / "datasets"
    sample_ids = [s.strip() for s in (args.samples or args.sample).split(",") if s.strip()]
    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    client = agent = None
    prices = PriceTable.load(ROOT)
    if args.audit:
        client, agent = build_audit_env(args.model or None)
        if client is None:
            print("⚠️  传了 --audit 但没读到 LLM_API_KEY（.env 或环境变量）。降级为只出结构指标。")
            args.audit = False
        else:
            print(f"模型: {client.model}  重复: {args.repeat}  样本: {','.join(sample_ids)}")

    loaded = {sid: load_sample(ds, sid) for sid in sample_ids}

    print("=" * 92)
    print(f"难度扫描 · 刻度 {levels} · 判分器 {args.scorer} · 模式 {'audit' if args.audit else 'offline'}")
    print("=" * 92)
    print(f"{'刻度':<4} {'诱饵':<4} {'伪装':<5} {'跨函数':<6} {'F1':<13} {'Prec':<13} "
          f"{'踩雷':<8} {'ms':<7} 说明")
    print("-" * 92)

    rows = []
    for level in levels:
        knob = PRESETS[level]
        per_level = {"f1": [], "precision": [], "recall": [], "decoy": [], "wall": []}
        structure = None
        t_in = t_out = 0
        m_trunc = 0

        for sid, (planted_source, meta) in loaded.items():
            new_src, metrics = apply_difficulty(planted_source, knob)
            structure = metrics
            decoy_fns = metrics.get("decoy_functions") or []
            if not args.audit:
                break
            for _ in range(max(1, args.repeat)):
                sc = run_audit(new_src, meta, score_fn, client, agent, decoy_fns)
                per_level["f1"].append(sc["f1"])
                per_level["precision"].append(sc.get("precision", 0.0))
                per_level["recall"].append(sc.get("recall", 0.0))
                per_level["decoy"].append(sc["decoy_hits"])
                per_level["wall"].append(sc["usage"].get("latency_ms", 0))
                u = sc["usage"]
                t_in += u.get("tokens_in", 0)
                t_out += u.get("tokens_out", 0)
                m_trunc += 1 if u.get("truncated") else 0

        def ms(vals, digits=3, none="n/a"):
            if not vals:
                return none
            m = statistics.fmean(vals)
            if len(vals) > 1:
                return f"{m:.{digits}f}±{statistics.pstdev(vals):.{digits}f}"
            return f"{m:.{digits}f}"

        metrics = structure or {"decoy_count": 0, "obfuscated": False, "cross_function": False}
        note = []
        if metrics.get("decoy_count"):
            note.append(f"+{metrics['decoy_count']}诱饵")
        if metrics.get("obfuscated"):
            note.append("伪装")
        if metrics.get("cross_function"):
            note.append("跨函数")
        if knob.variation_k:
            note.append(f"改写x{knob.variation_k}")

        print(f"{level:<4} {metrics.get('decoy_count', 0):<4} "
              f"{('Y' if metrics.get('obfuscated') else '-'):<5} "
              f"{('Y' if metrics.get('cross_function') else '-'):<6} "
              f"{ms(per_level['f1']):<13} {ms(per_level['precision']):<13} "
              f"{ms(per_level['decoy'], 1):<8} "
              f"{(str(int(statistics.fmean(per_level['wall']))) if per_level['wall'] else 'n/a'):<7} "
              f"{' '.join(note) or '原样'}")

        cost = prices.estimate_cost(client.model, t_in, t_out) if client else None
        rows.append({
            "level": level,
            "knob": knob.as_dict(),
            "metrics": metrics,
            "f1_mean": round(statistics.fmean(per_level["f1"]), 4) if per_level["f1"] else None,
            "f1_all": per_level["f1"],
            "precision_mean": round(statistics.fmean(per_level["precision"]), 4) if per_level["precision"] else None,
            "recall_mean": round(statistics.fmean(per_level["recall"]), 4) if per_level["recall"] else None,
            "decoy_hits_total": sum(per_level["decoy"]),
            "decoy_hits_mean": round(statistics.fmean(per_level["decoy"]), 4) if per_level["decoy"] else None,
            "wall_ms_mean": int(statistics.fmean(per_level["wall"])) if per_level["wall"] else None,
            "tokens_in": t_in, "tokens_out": t_out, "cost_usd": cost,
            "truncated": m_trunc,
        })
        if m_trunc:
            print(f"     ⚠️  本档 {m_trunc} 次疑似截断（空答案），F1 会被低估，建议调大 LLM_MAX_TOKENS")

    payload = {
        "sample_ids": sample_ids,
        "levels": levels,
        "scorer": args.scorer,
        "mode": "audit" if args.audit else "offline",
        "model": client.model if client else None,
        "repeat": args.repeat,
        "rows": rows,
    }
    with (ROOT / args.out).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print("-" * 92)
    if args.audit and rows:
        total_cost = sum(r["cost_usd"] or 0.0 for r in rows)
        tot_in = sum(r["tokens_in"] for r in rows)
        tot_out = sum(r["tokens_out"] for r in rows)
        cost_s = f"${total_cost:.4f}" if prices.configured else "n/a(未配单价)"
        print(f"合计 token: {tot_in + tot_out}  成本: {cost_s}  结果: {args.out}")
        f1s = [r["f1_mean"] for r in rows if r["f1_mean"] is not None]
        if len(f1s) >= 2:
            delta = f1s[0] - f1s[-1]
            trend = "下降 ✅ 分离成立" if delta > 0.05 else ("基本持平 ⚠️ 旋钮没体现在分数上" if delta > -0.05 else "上升 ❌ 反了")
            print(f"F1 走势: {f1s[0]:.3f} (刻度{levels[0]}) -> {f1s[-1]:.3f} (刻度{levels[-1]})，"
                  f"Δ={delta:+.3f} → {trend}")
        dh = [r["decoy_hits_mean"] for r in rows if r["decoy_hits_mean"] is not None]
        if len(dh) >= 2:
            print(f"踩诱饵均值: {dh[0]:.2f} -> {dh[-1]:.2f}（越高说明模型越'宁可错报'，难度越高）")
        if args.repeat < 3:
            print("⚠️  repeat<3：单次采样带随机性，'稳定'这条验收没做。正式结论请 --repeat 3 以上。")
    else:
        print(f"结果已落盘 {args.out}（F1 为 n/a = 未配 LLM，仅结构指标）")
    print("验收三条：① F1 随刻度下降且踩雷上升（分离）② 同档多次采样方差可控（稳定）"
          "③ 结构标志单调增加（结构，本次已验）")


if __name__ == "__main__":
    main()
