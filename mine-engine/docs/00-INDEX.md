# AuLE · mine-engine 研究文档索引

> **项目名：AuLE = Adaptive Audit Last Exam**（自适应审计终局考试）
> 对标 **ALE / Agents' Last Exam**（Berkeley RDI, arXiv:2606.05405）。
>
> 一句话定位：**mine-engine 不是审计 Agent，是"会自己出题的考试院"**——
> 一台可持续产出**新鲜、可验证、抗污染**审计考题的引擎。
> 智能合约只是它落地的第一个赛道（adapter）。

---

## 文档地图

### 本次新增（2026-10-01，偏"对外能讲 + 科研 idea"）

| 编号 | 文档 | 读者 | 一句话 |
| --- | --- | --- | --- |
| 01 | [代码与资产现状审查](./01-code-review.md) | 接手的人 | 我们已经有什么、缺什么、代码里的坑在哪 |
| 02 | [研究演进脉络（新手向）](./02-evolution.md) | 完全新手 | 这个领域怎么从"人出题"走到"机器出题"，我们站在哪一格 |
| 03 | [生态调研：同行 benchmark 全景](./03-landscape.md) | 做定位的人 | **ALE** / Harbor / EVMbench / FinancialAuditBench / AuditFraudBench / FinAuditing |
| 04 | [三条赛道的数据设计](./04-three-tracks.md) | 要扩赛道的人 | 国家审计 / 企业审计 / 审计师，各自的"雷"和"验证器"怎么设计 |
| 05 | [科研 idea 清单](./05-ideas.md) | 要发论文的人 | 7 个 idea，含创新性/工作量/风险评分与优先级 |
| 06 | [工程改进与路线图](./06-roadmap.md) | 写代码的人 | M7–M10 排期 |
| — | [可视化报告 report.html](./report.html) | 所有人 | 一页看懂：痛点 / 脉络 / 定位 / 赛道 / idea / 路线图 |

### 已有沉淀（偏"内部设计决策"）

| 文档 | 内容 |
| --- | --- |
| [AuLE-设计文档.md](./AuLE-设计文档.md) | v0.3：三级考试体系、四维评分、已有实验结果（含 Level 2 打穿率） |
| [ALE-Harbor借鉴方案.md](./ALE-Harbor借鉴方案.md) | v0.4：ALE 三层难度/五阶段生产/Gate-and-score + Harbor 七阶段验证的逐条借鉴 |
| [AuLE-代码实现方案.md](./AuLE-代码实现方案.md) | v0.1：借鉴 DataFlow 的 Operator/Pipeline/Storage/Prompt 重构设计 |
| [AuLE-前沿调研报告.md](./AuLE-前沿调研报告.md) | 前沿调研 |
| [埋雷引擎MVP开发清单-智能合约审计.md](./埋雷引擎MVP开发清单-智能合约审计.md) | M0–M7 可执行开发清单与 DoD |

**两套文档的关系**：已有沉淀回答"我们怎么建"；本次新增回答"我们怎么讲、怎么发论文、怎么扩赛道"。

---

## 三分钟速读版

1. **行业痛点**：所有公开 benchmark 一发布就开始腐烂——题目泄漏进训练数据，分数虚高。
   - EVMbench 用 cutoff 后真实事故做无污染重测，Agent 表现断崖下跌
   - **ALE 自己都只公开 10% 的题目（150/1490）来防污染**
2. **我们的解法**：不让题"被背下来"，而是**每次考试现出题**——
   程序化埋雷 + 差分验证证明"雷真是这次埋的" + 固定 seed 可复现。
   代价是 ALE 只能公开 10%，我们**100% 可公开且不怕被背**。
3. **最强佐证**：Modus/UIUC/Stanford 的 FinancialAuditBench（2026）在财报审计赛道用了
   **完全同源**的方法论（合成 engagement + 差分隐私先验 + 1100 小时专家），
   11 个前沿模型 Pass@1 最高仅 69.17%。
4. **下一步**：四组件抽象（Generator/Operator/Validator/Scorer）做成跨赛道 adapter，
   覆盖国家审计、企业审计、审计师三条赛道，并接入 Harbor 成为行业标准兼容的任务集。

---

## 当前能力快照

| 项 | 状态 |
| --- | --- |
| Level 1 · Detect | ✅ 3 模型 F1=1.000，qwen3.8-max 0.857 → **区分度不足，已饱和** |
| Level 2 · Exploit | ✅ 打穿率 50–83%；**tx_origin 是终极区分题** |
| Level 3 · 端到端 | 🔨 多文件仓库 + 四维打分，刚起步 |
| 数据集 | 7 样本（3 雷 × {原题, 变体} + 1 诱饵）→ 目标 50+（MVP DoD） |
| Harbor 导出 | ✅ 本次新增（`run_harbor_export.py`） |
| 跨赛道 | 🔨 三条赛道契约已定义，实现待做 |

### Level 2 实测（关键数据，勿丢）

| 模型 | 打穿率 | 关键失败 |
| --- | --- | --- |
| qwen3.8-flash | 5/6 | tx_origin 变体 fail "not owner" |
| qwen3.8-max | 5/6 | tx_origin 原题 fail "not owner" |
| deepseek-v4-flash | 4/6 | reentrancy 变体 no_code；tx_origin 变体 fail |
| deepseek-v4-pro | 3/6 | reentrancy 截断；access_control 变体 no_code |

**三条发现（写论文要用）**：
1. **Detect 满分 ≠ Exploit 打穿**——同一个模型在两种模式下排名会变
2. **tx_origin 是终极区分题**——模型不知道 Foundry 要用 `vm.prank(sender, origin)` 双参模拟
3. **deepseek-v4-pro 打穿率（3/6）反而低于 flash（4/6）**——这不是推理能力问题，
   是长代码生成时 `max_tokens=4096` 不够导致**截断**（sample-0001 直接 `vm.deal(vict` 断掉）。
   ⚠️ 这是一个**评测假象**，若不修正会把"生成长度限制"误当成"能力差异"

---

## 项目内 prompt 资产清单（已全部审阅）

| 位置 | 资产 | 作用 |
| --- | --- | --- |
| `engine/agents/audit_agent.py::PROMPT_STRATEGIES` | `standard` / `conservative` / `aggressive` 三套 | 同一模型换审计策略做 A/B，测"宁缺毋滥 vs 宁多勿漏" |
| `engine/agents/level3_agent.py::_PROMPT` | 多文件仓库端到端审计 | 含"区分真漏洞和诱饵"指令 |
| `engine/agents/exploit_agent.py` | 让模型写 Foundry 攻击 PoC | 从"会说"升级到"能打穿" |
| `engine/operators/variation.py::VARIATION_SYSTEM` | 语义保持改写 | 一道题长出多个变体，解决"确定性算子=复制粘贴" |
| `engine/scorers/report_score.py::_TYPE_ALIASES` | 漏洞类型别名归一化表 | 判卷时的中英文别名词典（本次已修否定词误判 bug） |
