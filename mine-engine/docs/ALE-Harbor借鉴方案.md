# ALE 与 Harbor 深度借鉴方案
## AuLE v0.4

> 本文基于 ALE 论文（arXiv 2606.05405, Berkeley RDI, 2026.06）和 Harbor 官方文档（Terminal-Bench 2.0, 2026.09）的精读。

---

## 一、ALE 核心设计拆解

### 1.1 三层难度体系

| 层级 | 题数 | 前沿模型通过率 | 用途 | 我们对应 |
|---|---|---|---|---|
| Near-Term | 59 | ~30% | 短期排行榜、快速迭代 | Level 1（Detect） |
| Full-Spectrum | 55 | ~20% | 覆盖每个子领域，全面评测 | Level 2（Exploit） |
| Last-Exam | 36 | ~2.6% | 里程碑评测，长期天花板 | Level 3（端到端审计） |

**关键设计**：Last-Exam 层不是"更难的 Near-Term"，而是"大多数模型 0% 通过"的任务——它锚定的是长期研究方向，不是日常调参。

**我们的差距**：
- Level 1 现在模型 F1=1.0，太简单 → 应该归为"训练题"，不是评测题
- Level 2 打穿率 50-83%，接近 Near-Term
- Level 3 刚起步，两个模型满分 → 还没到 Last-Exam 难度

### 1.2 题目五阶段生产流程

```
专家出题 → 初筛 Review → 工程实现 → 最终 QC → 接受
```

每道题都要过：
1. **专家出题**：真实工作项目，不是人造题
2. **初筛**：会议式 review（accept/revise/reject）
3. **工程实现**：变成可执行的沙箱环境
4. **最终 QC**： reproducibility + 评分校准
5. **反作弊**：主动找"捷径"，堵死 reward hacking

**我们怎么借鉴**：
- 我们没有专家出题，但**埋雷引擎自动造题**就是我们的"专家"
- 初筛 = **AI filter**（便宜模型先做，全对的标太易）
- 工程实现 = **Foundry 差分验证**（健康版 revert / 埋雷版成功）
- 反作弊 = **诱饵设计**（模型误报诱饵扣分）

### 1.3 评分：反 LLM-as-judge

ALE 的铁律：
> 能代码判的，绝不用 LLM 判。必须用 LLM 时，用窄粒度 yes/no probe，不用整体打分。

七种 artifact 评分模式：

| 模式 | 判什么 | 我们对应 |
|---|---|---|
| Exact/hashed | flag/答案字符串 | PoC 跑通（test pass） |
| Structured tabular | 多字段 manifest | findings JSON 字段匹配 |
| Geometric | 3D 模型距离 | 不适用 |
| Visual | 截图对比 | 不适用 |
| Behavioral | 系统状态 dump | Foundry 测试后余额变化 |
| Free-text | rubric 评分 | 报告质量（仅少量） |
| Executable | 跑测试集 | Foundry forge test |

**Gate-and-score 模式**：
- 硬前置条件：PoC 必须编译通过 → 不通过直接 0 分
- 然后才评质量：打穿了几个雷、有没有误报诱饵

**我们现在的问题**：四维评分里"利用"维度只是检查 poc 字段非空，没有真正跑 Foundry。Level 2 已经做了（run_exploit.py），Level 3 要接上。

---

## 二、Harbor 核心设计拆解

### 2.1 七阶段任务验证流程

Harbor 的每个任务合并后还要过：

```
1. 贡献者提交（自测 + checklist）
2. CI 自动检查（oracle 解法过 / dummy 解法挂）
3. 专家人工 review
—— 合并 ——
4. 强大模型跑一遍，存轨迹
5. 人工审计轨迹
6. 对抗性攻击审计（主动找"作弊"解法）
7. 最终决定（接受 / 打回）
```

**关键洞察**：一个任务不是"写完就完了"，合并后还要被模型跑、被人审、被攻击测试。

**我们怎么借鉴**：

| Harbor 阶段 | 我们对应 | 现状 |
|---|---|---|
| 1. 贡献者提交 | 埋雷引擎生成 | ✅ 已有 |
| 2. CI 自动检查 | Foundry 差分（健康版 revert / 埋雷版 pass） | ✅ 已有 |
| 3. 专家 review | —— | ❌ 缺（我们自己审） |
| 4. 模型跑轨迹 | AI filter + 4 模型 baseline | ✅ 已有 |
| 5. 人工审计轨迹 | —— | ❌ 缺 |
| 6. 对抗性攻击审计 | AI filter 找太易题 | 🔨 部分有 |
| 7. 最终决定 | 题目进/出数据集 | 🔨 待加 |

### 2.2 云沙箱 + 任务版本化

- `harbor run -d terminal-bench@4.0`：任务按版本号跑
- 水平扩展到几千个容器
- 支持 RL rollout（不只是评测，还能训练）

**我们怎么借鉴**：
- 数据集用 git commit hash 版本化
- 远程服务器 43.143.231.106 部署 Foundry 容器
- 暂不做 RL，先把评测跑稳

---

## 三、我们的具体行动方案

### 3.1 短期（1-2 周）：把 ALE 的评分纪律搬过来

**Gate-and-score 改造**：

Level 3 评分改成：
```
Gate 1: 模型输出的 JSON 能解析吗？不能 → 0 分
Gate 2: 模型写的 PoC 能编译吗？不能 → 利用分 = 0，但识别分照算
Gate 3: PoC 跑了吗？跑了但 test fail → 利用分 = 0
—— 过了 gate 才评质量 ——
识别分：recall（真雷找全了吗）
定位分：报的函数名对吗
报告分：severity 对吗 + 诱饵误报了吗
```

### 3.2 中期（2-4 周）：补 Harbor 式验证

给每道埋雷题加"对抗性审计"：
1. 用最便宜的模型跑一遍，如果全对 → 标为太易，降权或删除
2. 检查模型有没有"cheat"：比如不读代码直接报所有函数都有漏洞
3. 每道题存 ground truth + PoC + 预期模型行为

### 3.3 长期：数据集版本化

```
datasets/
├── v0.1/          # 7 题（Level 1）
├── v0.2/          # 15 题（+ Level 2 exploit）
├── v0.3/          # 25 题（+ Level 3 多文件）
└── README.md      # 每个版本的 git hash、通过率、已知问题
```

---

## 四、对比总结表

| 维度 | ALE | Harbor/EVMbench | AuLE（我们） |
|---|---|---|---|
| 题目来源 | 250 行业专家 | 人工从真实审计挑 | 埋雷引擎自动生成 |
| 难度分层 | 3 层（Near/Full/Last） | 无 | 3 层（Level 1/2/3） |
| 评分方式 | 代码优先，LLM 兜底 | 二值 test pass/fail | 四维（识别/定位/利用/报告） |
| Gate 设计 | Gate-and-score | 无 | 待加（PoC 编译 gate） |
| 反作弊 | 对抗性审计 | CI + 专家 review | AI filter 筛易题 + 诱饵 |
| 任务版本 | 无版本化 | 语义版本（@4.0） | git commit hash |
| 云沙箱 | VM 快照 | Docker 容器 | 远程服务器 Foundry |
| LLM judge | 窄粒度 yes/no probe | 不用 | 待加（报告质量评分） |
