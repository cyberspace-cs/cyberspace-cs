# AuLE 前沿调研报告 v0.1
## ALE / Harbor / EVMbench / SWE-bench / DataFlow 对标分析

> 调研时间：2026-10-01。目标：找准 AuLE 在学术版图里的位置，明确差异化。

---

## 1. 前沿版图速览

| 项目 | 机构 | 核心贡献 | 最新水平 | 对我们的启发 |
|---|---|---|---|---|
| **ALE** (Agents' Last Exam) | UC Berkeley RDI | 1500+ 长程真实任务，55 行业，250+ 专家出题 | Last-Exam tier 前沿模型平均通过率仅 2.6% | "考试分级"思路的源头 |
| **Harbor** | Terminal-Bench 团队 | 云沙箱框架，支持 RL/SFT rollout，任务版本化 | Terminal-Bench 4.0 已基于 Harbor | 我们的 Foundry 沙箱是它的极简版 |
| **EVMbench** | OpenAI + Paradigm + OtterSec | 120 个真实合约漏洞，detect/patch/exploit 三模式 | 模型 detect 45.6%，exploit 72.2% | 我们直接对标，但它有缺陷 |
| **SWE-bench Verified** | Princeton | GitHub issue 修复 | Claude Opus 5 已 97%，饱和 | 通用代码题拉不开差距，垂直领域才有区分度 |
| **DataFlow** | 北大张文涛组 | LLM 数据处理框架，Operator/Pipeline/Storage 抽象 | 近 200 算子，6 个领域 pipeline | 我们的引擎架构直接借鉴 |
| **DataClawEval** | 学术界 | 数据工程 agent benchmark，强调执行验证 | 最好 74.9 分，无 agent 全能 | "执行验证 > LLM judge" 的思路 |

---

## 2. 逐个拆解

### 2.1 ALE (Agents' Last Exam) —— 我们的"考试"原型

**它做了什么**：
- 不是"考试题"，而是"真实工作项目"：按 O*NET/SOC 职业分类体系，13 个行业集群、55 个子领域
- 250+ 行业专家参与出题，每题都有"经济价值"
- 分三层：Core → Extended → Last-Exam（最难）
- 关键指标：**full pass rate**（端到端跑通，不是部分分）

**为什么难**：
- 长程任务（不是一问一答）
- 结果可验证（有客观 test）
- 专家知道什么算"做完"
- 前沿模型在 Last-Exam tier 平均只有 2.6% 全通过

**我们学什么**：
- ✅ 分级考试（Core/Extended/Last-Exam → 我们的 Level 1/2/3）
- ✅ 结果可验证（我们用 Foundry test 验证 PoC）
- ❌ 我们没有 250 个专家出题——**这就是"埋雷引擎"存在的意义：自动造题**

### 2.2 Harbor —— 沙箱执行框架

**它做了什么**：
- 每个任务一个 Docker 容器快照
- 支持 cloud 部署（Daytona/Modal）
- 任务版本化（harbor run -d terminal-bench@4.0）
- 支持 RL rollout（不是只读评测，还能训练）

**我们现在怎么做**：
- 本地 Foundry 跑 forge test，没有容器隔离
- 没有任务版本化
- 没有 RL 接口

**我们学什么**：
- 短期：把 Foundry 测试打包成独立 task（已有 PoC 测试文件）
- 中期：部署到远程服务器 43.143.231.106（已测 SSH 通）
- 长期：不做 RL，先把评测跑通

### 2.3 EVMbench —— 直接对标

**它做了什么**：
- 120 个漏洞，来自 40 个真实审计仓库（Code4rena 比赛）
- 三种模式：detect（找漏洞）、patch（修漏洞）、exploit（写 PoC 打穿）
- 用本地 Ethereum 执行环境做程序化评分

**已有论文批评它**（arXiv 2603.10795）：
- 评估范围窄：只测了 14 个 agent 配置
- 大多数模型只跑了 detect，没跑 exploit
- 缺乏"诱饵"设计——模型只要报"有漏洞"就能拿部分分

**我们的差异化**：
| 维度 | EVMbench | AuLE |
|---|---|---|
| 题目来源 | 人工从真实审计挑 120 个 | 埋雷引擎自动生成 |
| 分级 | 只有 detect/patch/exploit 三模式 | Level 1/2/3 考试分级 |
| 诱饵 | 无 | 有（sweep/emergencyWithdraw/togglePause） |
| 评分 | 二值（打穿/没打穿） | 四维（识别/定位/利用/报告） |
| AI filter | 无 | 有（便宜模型先筛易题） |
| 变体 | 无 | LLM 语义保持改写，测泛化 |

### 2.4 SWE-bench —— 为什么我们不做通用代码题

**现状**：Claude Opus 5 在 SWE-bench Verified 已经 97%。
**结论**：通用代码修复题已经饱和，再做没有学术贡献。
**我们的位置**：垂直领域（智能合约审计）才是蓝海——EVMbench 刚出，缺陷明显，我们有机会。

### 2.5 DataFlow —— 引擎架构

**核心抽象**（上一轮已调研）：
- OperatorABC / Storage / LLMServing / PromptABC / PipelineABC
- PyTorch 风格：`__init__` 定义算子，`forward()` 串联
- 每步缓存 JSONL，支持 resume_step

**我们已经在做的**：算子（ReentrancyInjector 等）、LLM 变体改写、去重 filter、Foundry 验证。
**要补的**：统一 OperatorABC 基类、Storage 缓存、Pipeline 类。

---

## 3. 我们的论文叙事

一句话：
> "EVMbench 证明了 AI 能审计合约，但它的题目是静态的、评分是二值的、没有诱饵、没有分级。我们提出 AuLE：一个动态生成、分级考试、四维评分、含诱饵的智能合约审计 benchmark。"

三个创新点：
1. **动态造题**：埋雷引擎自动生成 + AI filter 筛易题 + LLM 变体测泛化
2. **考试分级**：Level 1 识别 → Level 2 利用 → Level 3 端到端审计项目
3. **四维评分**：识别/定位/利用/报告，对标 CPA 综合阶段

---

## 4. 优化后的代码实现方案

基于以上调研，调整之前的方案：

### 4.1 优先级调整

| 优先级 | 任务 | 为什么 |
|---|---|---|
| P0 | 把 Level 3 难题做出来（StakingVault 业务逻辑雷） | 这是我们和 EVMbench 最大的差异 |
| P0 | 加诱饵误报评分 | EVMbench 没有，我们有 |
| P1 | 迁移到 OperatorABC/Pipeline 架构 | DataFlow 借鉴，但不阻塞实验。<br>🟡 **进度（2026-10-01 核对）**：算子统一抽象**已完成**（四算子均继承 `IssueOperator`），<br>剩余 storage/serving/prompt 未做，已降级为支线，详见 [代码实现方案 v0.2](./AuLE-代码实现方案.md) |
| P1 | 跑更多模型（至少 5 个） | EVMbench 被批评只测 14 个配置，我们要测够 |
| P2 | 远程沙箱部署 | Harbor 借鉴，中期做 |
| P2 | 加 patch 模式 | EVMbench 有，我们也应该有 |

### 4.2 数据集规模目标

- Level 1：20 题（3 类漏洞 × 3 变体 + 诱饵）
- Level 2：15 题（PoC 可验证的）
- Level 3：5 个多文件仓库（每个含 2-3 个真雷 + 2-3 个诱饵）
- 总计 ~40 题，每个题有 ground truth + PoC + 评分规则

### 4.3 实验设计

- 模型：至少 5 个（qwen3.8-flash/max, deepseek-chat/reasoner, 加一个开源模型如 GLM）
- 每个题跑 3 次取平均（我们发现随机波动大）
- 报告四维分数 + 打穿率 + 诱饵误报率
- 和 EVMbench 已发表结果对比（如果有同类型题）
