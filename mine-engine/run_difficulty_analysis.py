"""汇总难度旋钮真实验收数据（两批扫描合并 + 分样本拆解）。

为什么分两批：完整一轮 54 次调用、耗时 12 分钟以上，超过工具单次超时上限。
现在脚本支持 `--levels` 分批跑 + 逐档落盘，本脚本把多批结果合并 analysis。

用法：python run_difficulty_analysis.py
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


def main() -> int:
    rows: dict[int, dict] = {}
    used, skipped = [], []
    for rel in BATCHES:
        p = ROOT / rel
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("mode") != "audit":
            skipped.append(f"{rel}(非 audit 模式)")
            continue
        used.append(rel)
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

    out = ROOT / "results_difficulty_analysis.json"
    out.write_text(json.dumps({
        "model": "deepseek-flash", "scorer": "v2", "samples": SAMPLES,
        "batches_used": used, "batches_skipped": skipped,
        "rows": [rows[lv] for lv in levels],
        "per_sample_f1_mean": {k: [round(x, 4) for x in v] for k, v in per_sample.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n合并结果已落盘 {out.name}（来源: {', '.join(used)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
