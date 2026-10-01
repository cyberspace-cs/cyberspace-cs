# mine-engine · 研究文档索引

> 定位一句话：**mine-engine 不是审计 Agent，是"会自己出题的考试院"**——
> 一台可持续产出**新鲜、可验证、抗污染**审计考题的引擎。
> 智能合约只是它落地的第一个赛道（adapter）。

| 编号 | 文档 | 读者 | 一句话 |
| --- | --- | --- | --- |
| 01 | [代码与资产现状审查](./01-code-review.md) | 接手的人 | 我们已经有什么、缺什么、代码里的坑在哪 |
| 02 | [研究演进脉络（新手向）](./02-evolution.md) | 完全新手 | 这个领域怎么从"人出题"走到"机器出题"，我们站在哪一格 |
| 03 | [生态调研：同行 benchmark 全景](./03-landscape.md) | 做定位的人 | Harbor / EVMbench / FinancialAuditBench / AuditFraudBench / FinAuditing 对比 |
| 04 | [三条赛道的数据设计](./04-three-tracks.md) | 要扩赛道的人 | 国家审计 / 企业审计 / 审计师，各自的"雷"和"验证器"怎么设计 |
| 05 | [科研 idea 清单](./05-ideas.md) | 要发论文的人 | 7 个 idea，含创新性/工作量/风险评分与优先级 |
| 06 | [工程改进与路线图](./06-roadmap.md) | 写代码的人 | M7–M10 排期，先做什么后做什么 |

## 三分钟速读版

1. **行业痛点**：所有公开 benchmark 一发布就开始腐烂——题目会泄漏进训练数据，分数虚高。
   EVMbench 用 cutoff 后的真实事故做无污染重测，Agent 表现断崖下跌，就是证据。
2. **我们的解法**：不让题"被背下来"，而是**每次考试现出题**（程序化埋雷 + 差分验证 + 固定 seed 可复现）。
3. **最强佐证**：Modus/UIUC/Stanford 的 FinancialAuditBench（2026）在财报审计赛道用了**完全同源**的
   方法论（合成 engagement + 差分隐私先验 + 1100 小时专家），11 个前沿模型 Pass@1 最高仅 69.17%。
   说明"合成 + 可验证"这条路已被顶会级工作验证，而我们在**合约赛道 + 通用引擎**上已有先发实现。
4. **下一步**：把引擎的四组件抽象（Generator / Operator / Validator / Scorer）做成跨赛道 adapter，
   一口气覆盖国家审计、企业审计、审计师三条赛道，并接入 Harbor 成为行业标准兼容的评测任务集。

---

## 项目内 prompt 资产清单（已全部审阅）

仓库内没有独立的"GPT-6 提示词"文件，以下为实际存在的 prompt 资产，均为 A/B 实验变量：

| 位置 | 资产 | 作用 |
| --- | --- | --- |
| `engine/agents/audit_agent.py::PROMPT_STRATEGIES` | `standard` / `conservative` / `aggressive` 三套 | 同一模型换审计策略做 A/B，测"宁缺毋滥 vs 宁多勿漏" |
| `engine/agents/level3_agent.py::_PROMPT` | 多文件仓库端到端审计 | 含"区分真漏洞和诱饵"指令 |
| `engine/agents/exploit_agent.py` | 让模型写 Foundry 攻击 PoC | 从"会说"升级到"能打穿" |
| `engine/operators/variation.py::VARIATION_SYSTEM` | 语义保持改写 | 一道题长出多个变体，解决"确定性算子=复制粘贴" |
| `engine/scorers/report_score.py::_TYPE_ALIASES` | 漏洞类型别名归一化表 | 判卷时的中英文别名词典 |
