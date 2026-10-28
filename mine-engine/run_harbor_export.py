"""把 datasets 里的样本导出为 Harbor 任务集（instruction + sandbox + verifier）。

Harbor 是 Terminal-Bench 团队出品的评测执行器，正在成为行业标准的"跑分插座"。
导出后即可用 Harbor 加载：

    py run_harbor_export.py                       # detect 模式，导出到 harbor_tasks/
    py run_harbor_export.py --mode exploit        # exploit 模式（需 forge 镜像）
    py run_harbor_export.py --only sample-0001    # 只导出指定样本

    uv tool install harbor
    harbor run --dataset-path harbor_tasks --agent claude-code --model anthropic/claude-opus-4-1

产出结构（每个任务一个目录）：
    harbor_tasks/mine-sample-0001-detect/
    ├─ instruction.md            给 agent 的题
    ├─ task.toml                 registry 元数据
    ├─ environment/Dockerfile    沙箱
    ├─ environment/workspace/    agent 可见材料（不含 ground truth）
    ├─ solution/                 黄金解答（验证任务可解）
    └─ tests/                    verifier + ground_truth.json（agent 不可见）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.adapters.harbor import export_dataset  # noqa: E402
from engine.adapters.domains import DOMAIN_REGISTRY  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="导出 Harbor 任务集")
    ap.add_argument("--mode", default="detect", choices=["detect", "exploit"],
                    help="detect=判审计报告；exploit=判攻击 PoC（默认 detect）")
    ap.add_argument("--out", default="harbor_tasks", help="输出目录（默认 harbor_tasks/）")
    ap.add_argument("--only", default="", help="逗号分隔的 sample_id，默认全部")
    ap.add_argument("--version", default="0.1.0", help="数据集版本")
    ap.add_argument("--domain", default="smart-contract",
                    choices=sorted(DOMAIN_REGISTRY), help="赛道标识")
    args = ap.parse_args()

    only = [s.strip() for s in args.only.split(",") if s.strip()] or None
    out_dir = ROOT / args.out

    stats = export_dataset(
        ROOT, out_dir, mode=args.mode, only=only,
        version=args.version, domain=args.domain,
    )

    print("=" * 72)
    print(f"Harbor 导出 · mode={args.mode} · domain={args.domain} · version={args.version}")
    print("=" * 72)
    print(f"  样本总数: {stats.total}")
    print(f"  导出成功: {stats.exported}")
    if stats.skipped:
        print(f"  跳过 {len(stats.skipped)} 个:")
        for s in stats.skipped:
            print(f"    - {s}")
    print(f"  输出目录: {out_dir}")
    print()
    print("  下一步：")
    print("    uv tool install harbor")
    print(f"    harbor run --dataset-path {args.out} --agent <agent> --model <model>")
    print("=" * 72)
    return 0 if stats.exported else 1


if __name__ == "__main__":
    raise SystemExit(main())
