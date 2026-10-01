# 06 · 工程改进与路线图（M7–M10）

---

## 本次已落地（M7 第一批）

| # | 改动 | 文件 | 解决什么 |
| --- | --- | --- | --- |
| 1 | **放行 `docs/`** | `.gitignore` | 修 P0：文档此前被 gitignore 屏蔽，GitHub 上 `mine-engine/docs` 一直是 404 |
| 2 | **判分器修复** | `engine/scorers/report_score.py` | 修 P0：`non-reentrant` 被子串匹配误判为 TP；新增否定词检测 + 词边界匹配 + finding 去重 |
| 3 | **判分 v2** | `engine/scorers/report_score.py::score_report_v2` | 从"类型匹配"升级为 **类型 + 位置 IoU + 严重度加权** 三维打分 |
| 4 | **难度与抗污染分析** | `engine/analytics/difficulty.py` | 新增：实测难度、IRT(Rasch) 简化拟合、区分度、**CRS 抗污染分** |
| 5 | **Harbor 导出器** | `engine/adapters/harbor.py` + `run_harbor_export.py` | 把任意赛道样本导出成 `instruction.md + environment/ + tests/verifier` 三元组，对齐行业标准 |
| 6 | **重复实验** | `run_benchmark.py --repeat N` | 修 P1：单次采样无统计力，现支持多轮输出 mean±std |
| 7 | **赛道接口骨架** | `engine/adapters/domains.py` | 定义国家审计 / 企业审计 / 审计师三条赛道的 adapter 契约与算子清单 |

向后兼容：所有改动均为**新增为主、替换为辅**，`score_report` 保留旧签名，
现有 `run_*.py` 无需修改即可继续运行。

---

## M7 · 稳固地基（进行中，2 周）

**目标**：让"引擎"这件事能被反复讲、被别人复现。

- [x] 修 `.gitignore` 的 `docs/` 屏蔽
- [x] 判分器 bug 修复 + v2 打分
- [x] 难度/区分度/CRS 分析模块
- [x] Harbor 导出器（合约赛道）
- [x] `run_benchmark --repeat`
- [ ] **难度标签写回**：`run_ai_filter` 输出连续难度分，存 `datasets/filter_labels.jsonl`（不再写回 index，避免重跑丢失）
- [ ] **Manifest 化**：`datasets/manifest.json` 记录 seed / 算子版本 / solc 版本 / 生成时间，让"可复现"可被验证
- [ ] `run_level3.py` 参数化（去掉硬编码 deepseek）

**完成判据**：`py run_harbor_export.py` 能产出一批可直接被 Harbor 加载的任务目录。

---

## M8 · 规模与区分度（1 个月）

**目标**：从 7 题推到 100+ 题，并让强模型也开始丢分。

- [ ] 新增算子：`unchecked_call`（SWC-104）、`integer_error`（SWC-101）、`delegatecall`
- [ ] **组合雷**：同一合约埋 2–3 个雷，测"多目标召回"
- [ ] **更隐蔽诱饵**：看起来危险但实际安全（已有 Station 太明显）
- [ ] **Review 模式**（抄 FinancialAuditBench）：给模型一份"已完成的审计报告"，里面埋了错误结论，让它复核 → 成本更低、区分度更高
- [ ] 变体算子扩量：`LLM_VARIATIONS=5`，每题长 5 个变体
- [ ] 判分再升级：证据链评分（finding 是否给出可利用路径）

**完成判据**：100+ 题；至少 2 个前沿模型在完整集上 F1 < 0.9。

---

## M9 · 第二个 adapter（2 个月）

**目标**：证明四组件抽象**真的**跨赛道（这是最关键的一次验证）。

- [ ] **企业审计 adapter（L2）**
  - 合成制造业公司账套（总账 / 明细账 / 凭证 / 合同 / 银行流水）
  - 算子：收入提前确认 / 费用资本化 / 少提减值 / 循环交易
  - 验证器：三表勾稽 + 凭证链完整性 + 红旗指标越界（全确定性算术）
- [ ] Harbor 导出器泛化（抽象成 `BaseExporter`）
- [ ] **国家审计 adapter MVP（L3）**
  - 合成部门预算执行账套，3 类算子（虚假列支 / 规避招标 / 资金滞留）
  - 验证器：资金流勾稽 + 法规条款命中（双闸门）
  - ⚠️ 合规：只用公开公告做类型语料，真实数据仅提**差分隐私聚合先验**

**完成判据**：`engine/adapters/` 下有两个赛道实现，共用同一套 `Pipeline` 编排。

---

## M10 · 共演化与第四条赛道（3 个月+）

- [ ] 埋雷–审计共演化循环（I3）
- [ ] 审计师 adapter（L4，需持牌 CPA rubric）
- [ ] 自动化顺从评测集（I5）
- [ ] 与 `seven_-audit` 的 RSI 工作合流

---

## 原则（写给自己）

1. **先能说，再做深**。叙事层（文档 + Harbor 兼容）零代码就能拿分，优先做。
2. **规模是硬伤**。7 题不支撑任何结论，M8 之前不对外发布任何"模型能力"结论。
3. **不碰真实敏感数据**。所有赛道一律走"合成 + 差分隐私先验"，
   这是 FinancialAuditBench 已经验证的合规路径。
4. **新增算子不改编排层**。这是四组件抽象的价值所在，也是对外讲的核心。
   一旦出现"为了加一个算子改了 pipeline"，说明抽象漏了。
