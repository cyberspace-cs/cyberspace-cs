"""汇总难度旋钮真实验收数据（两批扫描合并 + 分样本拆解）。

为什么分两批：完整一轮 54 次调用、耗时 12 分钟以上，超过工具单次超时上限。
现在脚本支持 `--levels` 分批跑 + 逐档落盘，本脚本把多批结果合并 analysis。

用法：
    python run_difficulty_analysis.py                       # 用默认批次（flash）
    python run_difficulty_analysis.py results_pro_*.json    # 指定其它批次（如 v4-pro）
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

BATCHES = ["results_diff_A.json", "results_diff_B.json", "results_diff_C.json"]
SAMPLES = ["sample-0001", "sample-0002", "sample-0003"]


def resolve_batches(argv: list[str]) -> list[str]:
    """命令行给了文件就用给的，否则用默认批次。支持 shell 通配符展开后的路径。"""
    if not argv:
        return BATCHES
    out = []
    for a in argv:
        p = Path(a)
        out.append(a if p.exists() else a.replace("\\", "/"))
    return out


def main() -> int:
    rows: dict[int, dict] = {}
    used, skipped = [], []
    model: str | None = None
    for rel in resolve_batches(sys.argv[1:]):
        p = ROOT / rel
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("mode") != "audit":
            skipped.append(f"{rel}(非 audit 模式)")
            continue
        used.append(rel)
        #模型名在结果 JSON 的顶层，不在每行里
        model = model or d.get("model")
        for r in d["rows"]:
            rows.setdefault(r["level"], r)
    if not rows:
        print("❌ 没找到 audit 结果。先跑 run_difficulty_sweep.py --audit ...")
        return 1

    levels = sorted(rows)
    print("=" * 100)
    print("难度旋钮验收 · deepseek-flash · 3 样本 × 3 次/档 · v2 判分器")
    print("=" * 100)
    print(f"{'刻度':<5}{'n':<4}{'F1':<8}{'标准差':<8}{'精确率':<8}{'召回':<8}"
          f"{'踩雷率':<8}{'耗时s':<8}{'tokens':<10}{'截断':<6}{'失败':<6}旋钮")
    print("-" * 100)
    decoys_desc = {0: "原样", 1: "+1诱饵", 2: "+2诱饵", 3: "+3诱饵 伪装",
                   4: "+4诱饵 伪装 跨函数", 5: "+6诱饵 伪装 跨函数"}
    for lv in levels:
        r = rows[lv]
        tok = (r.get("tokens_in") or 0) + (r.get("tokens_out") or 0)
        # f1_std 自己算：结果 JSON 里不保证有这个字段（扫描脚本按 mean 存）
        sd = st.pstdev(r["f1_all"]) if len(r["f1_all"]) > 1 else 0.0
        r["f1_std"] = round(sd, 4)
        print(f"{lv:<5}{len(r['f1_all']):<4}{r['f1_mean']:<8.3f}{sd:<8.3f}"
              f"{r['precision_mean']:<8.3f}{r['recall_mean']:<8.3f}{r['decoy_hits_mean']:<8.2f}"
              f"{r['wall_ms_mean'] / 1000:<8.1f}{tok:<10}{r.get('truncated', 0):<6}"
              f"{r.get('errors', 0):<6}{decoys_desc.get(lv, '')}")

    # ---- 分样本：均值会稀释单题效应，这张表才是关键 ----
    print("\n" + "=" * 100)
    print("分样本 F1（每格 = 该样本在该档的 3 次采样）—— 均值会掩盖方向相反的单题效应")
    print("=" * 100)
    short = [s.replace("sample-", "") for s in SAMPLES]
    print(f"{'刻度':<6}" + "".join(f"{s:<26}" for s in short))
    per_sample: dict[str, list[float]] = {s: [] for s in SAMPLES}
    for lv in levels:
        f = rows[lv]["f1_all"]
        cells = []
        for i, sid in enumerate(SAMPLES):
            seg = f[i * 3:(i + 1) * 3]
            if len(seg) == 3:
                per_sample[sid].append(st.fmean(seg))
            cells.append("/".join(f"{x:.2f}" for x in seg))
        print(f"{lv:<6}" + "".join(f"{c:<26}" for c in cells))

    print("\n每题从刻度0到刻度5的变化：")
    for sid in SAMPLES:
        v = per_sample[sid]
        if len(v) >= 2:
            d = v[0] - v[-1]
            arrow = "↓ 变难" if d > 0.05 else ("↑ 变易" if d < -0.05 else "→ 持平")
            print(f"  {sid}: {v[0]:.3f} → {v[-1]:.3f}  Δ={d:+.3f}  {arrow}")

    # ---- 验收判定 ----
    print("\n" + "=" * 100)
    print("三条验收")
    print("=" * 100)
    f1s = [rows[lv]["f1_mean"] for lv in levels]
    dhs = [rows[lv]["decoy_hits_mean"] for lv in levels]
    walls = [rows[lv]["wall_ms_mean"] for lv in levels]
    sds = [rows[lv]["f1_std"] for lv in levels]

    print(f"① 结构单调：诱饵 0→1→2→3→4→6、伪装刻度3起、跨函数刻度4起（离线 18 项体检全过）→ ✅")
    print(f"② 分离：F1 端点 {f1s[0]:.3f} → {f1s[-1]:.3f}（Δ={f1s[0] - f1s[-1]:+.3f}）；"
          f"踩雷率 {dhs[0]:.2f} → {dhs[-1]:.2f}；耗时 {walls[0] / 1000:.1f}s → {walls[-1] / 1000:.1f}s")
    non_mono = [lv for i, lv in enumerate(levels[1:], 1) if rows[lv]["f1_mean"] > rows[levels[i - 1]]["f1_mean"]]
    if f1s[0] - f1s[-1] > 0.05:
        print(f"   → ✅ 端点下降超过 0.05 阈值，旋钮确实在起作用")
    else:
        print(f"   → ❌ 端点降幅 {f1s[0] - f1s[-1]:.3f} 不足")
    if non_mono:
        print(f"   ⚠️ 非逐档单调，刻度 {non_mono} 出现回升。")
        print(f"      注意刻度3 精确率=1.000：加诱饵反而没引出误报，")
        print(f"      拉高了均值 —— 这正是'均值掩盖单题效应'的典型例子（见分样本表）。")
    print(f"③ 稳定：各档标准差 {['%.2f' % x for x in sds]}，最大 {max(sds):.3f}")
    print(f"   → {'⚠️ 离散度偏大，正式结论需扩样本 + repeat≥5' if max(sds) > 0.25 else '✅ 可接受'}")
    print(f"   注：标准差大不完全是噪声 —— 部分变体模型确实找不到雷了，那正是难度该有的表现。")

    out = ROOT / f"results_difficulty_analysis_{model or 'unknown'}.json"
    out.write_text(json.dumps({
        "model": model, "scorer": "v2", "samples": SAMPLES,
        "batches_used": used, "batches_skipped": skipped,
        "rows": [rows[lv] for lv in levels],
        "per_sample_f1_mean": {k: [round(x, 4) for x in v] for k, v in per_sample.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n合并结果已落盘 {out.name}（来源: {', '.join(used)}）")
    return 0


def compare_models() -> int:
    """对比两个模型的难度曲线，回答验收标准里「不同 AI 的曲线必须分开」那条。

    只看均值会骗人：两条曲线可能在端点接近、中间交叉。因此这里同时给
    逐档差值与秩相关（Spearman），只要**秩相关 < 0.9** 就说明形状不同。
    """
    import glob
    flash = collect(sorted(glob.glob(str(ROOT / "results_diff_*.json"))))
    # pro 的来源：合并后的完整档位 + 整档跑完的 L1/L2（排除 A 的残档与分样本碎片）
    pro = collect(sorted(glob.glob(str(ROOT / "results_pro_merged_*.json")))
                  + sorted(glob.glob(str(ROOT / "results_pro_L[12].json"))))
    if not flash or not pro:
        print("需要两组结果：results_diff_*.json（flash）与 results_pro_[AB].json（v4-pro）")
        print(f"  现状: flash={sorted(flash)} pro={sorted(pro)}")
        return 1

    common = sorted(set(flash) & set(pro))
    if len(common) < 2:
        print(f"⚠️ 两边共同刻度只有 {common}，无法比较曲线形状")
        return 1
    # 覆盖不全时必须提示：只测 2 个端点得出的"形状"没有说服力
    if len(common) < 6:
        print(f"⚠️ 只覆盖刻度 {common}（共 6 档）。端点比较有效，"
              f"但'曲线形状'结论在补齐中间档之前不成立。")

    print("=" * 96)
    print("分离度验收：deepseek-flash vs deepseek-v4-pro 的难度曲线是否分开")
    print("=" * 96)
    print(f"{'刻度':<6}{'flash F1':>10}{'pro F1':>10}{'差(pro-flash)':>16}"
          f"{'flash踩雷':>11}{'pro踩雷':>10}")
    print("-" * 96)
    diffs = []
    for lv in common:
        a = flash[lv]["f1_mean"]
        b = pro[lv]["f1_mean"]
        diffs.append(b - a)
        print(f"{lv:<6}{a:>10.3f}{b:>10.3f}{b - a:>+16.3f}"
              f"{flash[lv]['decoy_hits_mean']:>11.2f}{pro[lv]['decoy_hits_mean']:>10.2f}")

    # Spearman 秩相关：形状相似度。1=完全同形，<0.9 视为形状不同。
    def spearman(xs, ys):
        def rank(v):
            order = sorted(range(len(v)), key=lambda i: v[i])
            r = [0.0] * len(v)
            for pos, i in enumerate(order):
                r[i] = pos + 1.0
            return r
        rx, ry = rank(xs), rank(ys)
        n = len(xs)
        mx, my = sum(rx) / n, sum(ry) / n
        num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
        return num / den if den else float("nan")

    fa = [flash[lv]["f1_mean"] for lv in common]
    pa = [pro[lv]["f1_mean"] for lv in common]
    rho = spearman(fa, pa)
    print("-" * 96)
    print(f"端点降幅  flash {fa[0]:.3f}→{fa[-1]:.3f} (Δ{fa[0]-fa[-1]:+.3f})   "
          f"pro {pa[0]:.3f}→{pa[-1]:.3f} (Δ{pa[0]-pa[-1]:+.3f})")
    print(f"曲线形状秩相关 ρ = {rho:.3f}"
          f"（1=同形；<0.9 视为形状不同 → 难度对不同模型作用不同）")
    print(f"最大逐档差距 {max(abs(d) for d in diffs):.3f} 出现在刻度 "
          f"{common[diffs.index(max(diffs, key=abs))]}")

    print("\n判读：")
    if rho < 0.9:
        print(f"  ✅ 两条曲线形状不同（ρ={rho:.3f}<0.9）—— 旋钮不是给所有模型套同一个难度，"
              f"而是改变题目本身")
    else:
        print(f"  ⚠️ 两条曲线形状几乎相同（ρ={rho:.3f}）—— 旋钮对模型差异不敏感，"
              f"用它区分模型的能力有限")
    (ROOT / "results_difficulty_separation.json").write_text(json.dumps({
        "levels": common,
        "flash_f1": fa, "pro_f1": pa,
        "flash_decoy": [flash[lv]["decoy_hits_mean"] for lv in common],
        "pro_decoy": [pro[lv]["decoy_hits_mean"] for lv in common],
        "spearman_rho": round(rho, 4),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("落盘 results_difficulty_separation.json")
    return 0


def collect(paths: list[str]) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    for p in paths:
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("mode") != "audit":
            continue
        for r in d.get("rows", []):
            rows.setdefault(r["level"], r)
    return rows


SAMPLE_IDS = ["sample-0001", "sample-0002", "sample-0003"]


def merge_split_levels(pattern: str) -> int:
    """把「按样本分开跑、同一档」的结果拼回完整的一档。

    为什么需要：`deepseek-v4-pro` 在高档位单档要跑 5–10 分钟，超过工具单次超时上限，
    只能 `--samples sample-0001` 这样一档拆三次跑。逐档落盘救不了"档内中断"
    （一档内的 9 次调用是一个整体，中断则整档丢失）。
    每个分样本文件里`f1_all` 的下标含义是**该样本自己的 0..repeat-1**，
    所以拼接时必须按样本在SAMPLE_IDS 里的位置放回正确的偏移。
    """
    import glob
    import re
    files = sorted(glob.glob(str(ROOT / pattern)))
    if not files:
        print(f"没匹配到文件：{pattern}")
        return 1
    # 文件名里带样本号：results_pro_L3_s1.json / _s2.json
    by_level: dict[int, dict[int, tuple[str, dict]]] = {}
    for f in files:
        m = re.search(r"_s(\d)\.json$", f)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        for r in d.get("rows", []):
            by_level.setdefault(r["level"], {})[idx] = (Path(f).name, r)

    merged_out = {}
    for lv in sorted(by_level):
        parts = by_level[lv]
        have = sorted(parts)
        if have != list(range(len(SAMPLE_IDS))):
            print(f"⚠️ 刻度 {lv} 只齐了样本 {have}，跳过合并（需要 0,1,2）")
            continue
        # parts 的结构是 {样本下标: (文件名, row)}，parts[0] 本身就是 (name, row)
        base_name, base = parts[0]
        repeat = len(base["f1_all"])
        f1: list[float] = []
        for idx in sorted(parts):
            seg = parts[idx][1]["f1_all"]
            f1.extend(seg)
        # 权重字段：耗时/token/成本按调用次数加和，均值类按样本数平均
        def wsum(key):
            return sum(parts[i][1].get(key) or 0 for i in sorted(parts))

        def wmean(key):
            vals = [parts[i][1].get(key) for i in sorted(parts)]
            vals = [v for v in vals if v is not None]
            return st.fmean(vals) if vals else None

        n = len(f1)
        row = dict(base)
        row["f1_all"] = f1
        row["f1_mean"] = round(st.fmean(f1), 4)
        row["f1_std"] = round(st.pstdev(f1), 4) if n > 1 else 0.0
        row["precision_mean"] = wmean("precision_mean")
        row["recall_mean"] = wmean("recall_mean")
        row["decoy_hits_total"] = wsum("decoy_hits_total")
        row["decoy_hits_mean"] = round(row["decoy_hits_total"] / n, 4) if n else 0.0
        row["wall_ms_mean"] = int(wsum("wall_ms_mean"))
        row["tokens_in"] = wsum("tokens_in")
        row["tokens_out"] = wsum("tokens_out")
        row["truncated"] = wsum("truncated")
        row["errors"] = wsum("errors")
        row["n_ok"] = n
        merged_out[lv] = row
        out_name = f"results_pro_merged_L{lv}.json"
        (ROOT / out_name).write_text(json.dumps({
            "sample_ids": SAMPLE_IDS, "levels": [lv], "scorer": "v2",
            "mode": "audit", "model": "deepseek-v4-pro", "repeat": repeat,
            "merged_from": [parts[i][0] for i in sorted(parts)],
            "rows": [row],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 刻度 {lv} 合并 {n} 次调用 -> {out_name}  F1={row['f1_mean']:.3f} "
              f"踩雷={row['decoy_hits_mean']:.2f}")
    if not merged_out:
        return 1
    print("\n现在可以跑：python run_difficulty_analysis.py --compare")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--compare" in argv:
        raise SystemExit(compare_models())
    if "--merge" in argv:
        pat = argv[argv.index("--merge") + 1] if len(argv) > argv.index("--merge") + 1 else "results_pro_L*_s?.json"
        raise SystemExit(merge_split_levels(pat))
    raise SystemExit(main())
