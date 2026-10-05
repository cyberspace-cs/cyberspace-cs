"""离线自测：不连任何真实 API，验证"时间与成本记账"整条链路是通的。

为什么需要它：
  本机没有 .env（也就没有 API key），无法真跑一次 benchmark 来验收第一步。
  但记账链路是否正确，跟模型回答得对不对**无关**——
  只要把 LLM 客户端换成假的、让它返回带 usage 的响应，就能验证：
    · usage 有没有被透传出来（而不是像以前那样被丢掉）
    · wall_ms 有没有记
    · 成本算得对不对
    · cost per solved task 的口径对不对（分母只算做对的题）
    · 没配单价表时是不是老实显示 n/a，而不是假装 0

用法：
    py run_offline_smoke.py
退出码 0 = 全部通过。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ---- 假环境：不能留下任何真实密钥的痕迹 -------------------------------------
os.environ["LLM_BASE_URL"] = "http://offline.invalid/v1"
os.environ["LLM_API_KEY"] = "offline-not-a-real-key"
os.environ["LLM_MODELS"] = "fake-perfect,fake-empty"
os.environ["LLM_PRICES"] = json.dumps({
    "fake-perfect": {"in": 1.0, "out": 4.0},   # USD / 百万 token
    "fake-empty": {"in": 1.0, "out": 4.0},
})

from engine.llm.client import LLMClient, LLMResponse, Usage  # noqa: E402

# 每个模型的假回答：perfect 报一个 reentrancy，empty 什么都不报
FAKE_ANSWERS = {
    "fake-perfect": '{"findings":[{"vuln_type":"reentrancy","function":"withdraw",'
                    '"line":20,"severity":"critical","evidence":"state updated after call"}]}',
    "fake-empty": '{"findings":[]}',
}
# 假用量：输入 12,000 token、输出 300 token（真实量级）
FAKE_USAGE = {"prompt_tokens": 12000, "completion_tokens": 300}


def fake_chat_detailed(self, messages, max_tokens: int = 1024, retries: int = 2):
    """替换掉真实网络请求。签名与真实方法一致。"""
    import time
    t0 = time.time()
    time.sleep(0.005)  # 模拟一点网络往返，好让 wall_ms 不是 0
    text = FAKE_ANSWERS.get(self.model, '{"findings":[]}')
    resp = LLMResponse(
        text=text,
        usage=Usage(tokens_in=FAKE_USAGE["prompt_tokens"],
                    tokens_out=FAKE_USAGE["completion_tokens"],
                    raw=dict(FAKE_USAGE)),
        model=self.model,
        latency_ms=int((time.time() - t0) * 1000),
    )
    self._record(resp)
    return resp


LLMClient.chat_detailed = fake_chat_detailed


def main() -> int:
    import run_benchmark

    print("=" * 78)
    print("离线自测 · 时间与成本记账（不连真实 API）")
    print("=" * 78)

    sys.argv = ["run_benchmark.py", "--out", "results_offline_smoke.json",
                "--solved-threshold", "0.5"]
    run_benchmark.main()

    out = ROOT / "results_offline_smoke.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    summary = {r["model"]: r for r in data["summary"]}

    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))
        print(f"  {'✅' if cond else '❌'} {name}" + (f"  —— {detail}" if detail else ""))

    print("\n" + "=" * 78)
    print("断言")
    print("=" * 78)

    # 1. usage 透传：token 数必须非 0（这是以前做不到的）
    for m, r in summary.items():
        check(f"[{m}] tokens_in 非 0（usage 透传成功）", r["tokens_in"] > 0,
              f"tokens_in={r['tokens_in']}")
        check(f"[{m}] tokens_out 非 0", r["tokens_out"] > 0,
              f"tokens_out={r['tokens_out']}")

    # 2. 墙钟时间
    check("[全部] wall_ms 已记录", all(r["wall_ms"] >= 0 for r in summary.values()),
          f"fake-perfect={summary['fake-perfect']['wall_ms']}ms")

    # 3. 成本：配置了单价表，必须算得出来
    check("[全部] cost_usd 不是 None（已配单价表）",
          all(r["cost_usd"] is not None for r in summary.values()),
          f"fake-perfect=${summary['fake-perfect']['cost_usd']}")

    # 4. cost per solved task 口径
    pe, em = summary["fake-perfect"], summary["fake-empty"]
    check("fake-perfect 至少做对一部分题（solved>0）", pe["solved"] > 0,
          f"solved={pe['solved']}/{pe['n_tasks']}")
    # ⚠️ 注意：fake-empty 什么都不报，但在**chaff 题**上这恰恰是正确答案（F1=1.0）。
    # 所以它 solved=1 而不是 0 —— 这不是 bug，是chaff 题判分正确的证据。
    check("fake-empty 只在chaff 题上得分（其余全漏报）", em["solved"] == 1,
          f"solved={em['solved']}/{em['n_tasks']}（唯一答对的是 sample-0004 chaff 题）")
    check("做对题时 cost_per_solved = 总成本 ÷ 成功数",
          pe["cost_per_solved_usd"] is not None
          and abs(pe["cost_per_solved_usd"] - pe["cost_usd"] / pe["solved"]) < 1e-6,
          f"{pe['cost_usd']} ÷ {pe['solved']} = {pe['cost_per_solved_usd']}")

    # ---- 第二轮：只跑非chaff 题，制造真正的 solved=0，验证不除零 --------------
    print("\n" + "-" * 78)
    print("第二轮：只跑非chaff 题（fake-empty 应该一道都做不对）")
    print("-" * 78)
    sys.argv = ["run_benchmark.py", "--out", "results_offline_smoke2.json",
                "--only", "sample-0001,sample-0002,sample-0003"]
    run_benchmark.main()
    data2 = json.loads((ROOT / "results_offline_smoke2.json").read_text(encoding="utf-8"))
    em2 = {r["model"]: r for r in data2["summary"]}["fake-empty"]
    check("纯非chaff 题上 fake-empty solved=0", em2["solved"] == 0,
          f"solved={em2['solved']}/{em2['n_tasks']}")
    check("solved=0 时 cost_per_solved 为 None（不能除零）",
          em2["cost_per_solved_usd"] is None, f"={em2['cost_per_solved_usd']}")
    check("但总成本仍然如实记录（花了钱，只是没做对）",
          em2["cost_usd"] is not None and em2["cost_usd"] > 0,
          f"cost_usd=${em2['cost_usd']}")

    # 5. 没配单价表时必须老实返回 None
    from engine.llm import PriceTable
    t = PriceTable()
    check("未配单价表时 estimate_cost 返回 None（不假装 0）",
          t.estimate_cost("fake-perfect", 12000, 300) is None)

    # 6. load_dotenv 传目录不能崩（曾把目录当文件读，抛 PermissionError）
    from engine.llm import load_dotenv
    probe = ROOT / "results_offline_smoke.env"
    probe.write_text("SMOKE_ENV_PROBE=ok\n", encoding="utf-8")
    try:
        n_dir = load_dotenv(probe.parent / "no_such_dir_marker")  # 不存在的目录 -> 0
        # 造一个"目录里的 .env"：直接把 probe 当目录不可能，改测文件路径与目录两种入参
        n_file = load_dotenv(probe)
        loaded_ok = os.environ.get("SMOKE_ENV_PROBE") == "ok"
        check("load_dotenv 接受 .env 文件路径", n_file == 1 and loaded_ok,
              f"n={n_file} value={os.environ.get('SMOKE_ENV_PROBE')!r}")
        check("load_dotenv 对不存在的路径返回 0（不抛异常）", n_dir == 0, f"n={n_dir}")
        os.environ.pop("SMOKE_ENV_PROBE", None)
    finally:
        probe.unlink(missing_ok=True)

    # 7. max_tokens 必须"运行时"读 LLM_MAX_TOKENS。
    #    踩过的坑：签名写成 `max_tokens: int = DEFAULT_MAX_TOKENS`（定义时求值），
    #    于是 LLMClient(model=...) 直接构造时完全无视环境变量，设 8192 仍按 4096 跑，
    #    难题上 thinking 烧满预算 -> 空答案 -> 分数悄悄变 0。
    from engine.llm import LLMClient
    from engine.llm.client import DEFAULT_MAX_TOKENS
    prev_mt = os.environ.get("LLM_MAX_TOKENS")
    try:
        os.environ["LLM_MAX_TOKENS"] = "12345"
        c_env = LLMClient(base_url="http://x/v1", api_key="k", model="m")
        check("直接构造 LLMClient 也认 LLM_MAX_TOKENS（不是定义时求值）",
              c_env.max_tokens == 12345, f"={c_env.max_tokens}")
        c_expl = LLMClient(base_url="http://x/v1", api_key="k", model="m", max_tokens=777)
        check("显式传 max_tokens 优先于环境变量", c_expl.max_tokens == 777,
              f"={c_expl.max_tokens}")
        os.environ["LLM_THINKING"] = "off"
        check("直接构造也认 LLM_THINKING", LLMClient(
            base_url="http://x/v1", api_key="k", model="m").thinking == "off")
        del os.environ["LLM_THINKING"]
        os.environ.pop("LLM_MAX_TOKENS", None)
        c_def = LLMClient(base_url="http://x/v1", api_key="k", model="m")
        check("没设环境变量时回落到 DEFAULT_MAX_TOKENS",
              c_def.max_tokens == DEFAULT_MAX_TOKENS, f"={c_def.max_tokens}")
    finally:
        if prev_mt is None:
            os.environ.pop("LLM_MAX_TOKENS", None)
        else:
            os.environ["LLM_MAX_TOKENS"] = prev_mt
        os.environ.pop("LLM_THINKING", None)

    print("\n" + "=" * 78)
    failed = [n for n, ok, _ in checks if not ok]
    if failed:
        print(f"❌ {len(failed)}/{len(checks)} 项未通过：")
        for n in failed:
            print("   -", n)
        return 1
    print(f"✅ 全部 {len(checks)} 项通过")
    print("说明：本自测用假 LLM 验证记账链路，与模型真实能力无关。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
