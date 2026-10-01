# AuLE: Adaptive Audit Last Exam
## 智能合约审计大模型能力考试 · 设计文档 v0.3

> 一个"动态对抗审计考试" benchmark：不只是考模型"认不认识漏洞"，而是考它能不能像真实审计师一样，端到端地完成审计项目——读代码、列风险、写 PoC 打穿、出报告。

> **v0.3 审查记录**：修正了 ① 评分维度中"定位"当前未实现的标注；② deepseek-v4-pro 打穿率反直觉的原因（长代码截断，非推理问题）；③ 明确 Level 3 中模型不知道雷数、我们知道；④ 补充诱饵题在 Level 2 不测 Exploit 的说明；⑤ 明确组合雷的 recall 口径。

---

## 1. 为什么做这个

### 1.1 问题
现有代码 LLM benchmark（HumanEval、SWE-bench、Terminal-Bench、EVMbench）在智能合约审计方向上有两个缺口：
- **Detect 模式饱和**：单文件、教科书级漏洞（重入/权限/tx.origin），前沿模型 F1 已接近 1.0，拉不开差距。
- **缺少"考试分级"思维**：没有从初级到高级的梯度，一道题要么满分要么零分，无法刻画模型能力曲线。

### 1.2 我们的主张
借鉴**真实审计职业考试**（中国审计署资格考试、CPA、CIA）的分级和评分逻辑，结合 **HLE 的 AI filter** 和 **EVMbench 的 Exploit 模式**，构建一个：
- **三级递进**的考试（初/中/高），每级考察不同能力；
- **四维评分**（识别/定位/利用/报告），不是一刀切对错；
- **动态对抗**：题目由埋雷引擎自动生成，AI filter 自动筛掉太易题，Exploit PoC 程序化验证。

---

## 2. 三级考试体系（对标审计职业考试）

| 级别 | 审计署对标 | 考什么 | 题目形态 | 评测方式 | 状态 |
|---|---|---|---|---|---|
| **Level 1 · 初级** | 初中级客观题 | 认识已知漏洞模式 | 单文件 ~30 行，单漏洞 | Detect：输出漏洞类型 JSON | ✅ 已完成 |
| **Level 2 · 中级** | 客观题+简单案例 | 把漏洞真正打穿 | 单文件，模型写 Foundry PoC | Exploit：编译+运行 PoC，打穿才算对 | ✅ 已完成 |
| **Level 3 · 高级** | 《高级审计实务》主观题 | 端到端审计项目 | 多文件仓库（多合约+继承+库），含诱饵+组合雷 | 完整流程：通读→列风险→写 PoC→出报告，四维评分 | 🔨 设计中 |

### Level 3 详细设计
给模型一个**完整仓库**（不是单文件），包含：
- 3-5 个合约（有继承、有库调用、有跨合约交互）
- 埋 1-2 个真雷（可能组合：重入+权限缺失）
- 埋 1-2 个诱饵（看起来危险但实际安全）
- **不告诉模型有几个雷、哪几个文件有雷**（我们知道，用于评分）

要求模型输出一份**结构化审计报告**：
```json
{
  "findings": [
    {
      "vuln_type": "reentrancy",
      "contract": "Vault.sol",
      "function": "withdraw",
      "line": 42,
      "severity": "critical",
      "evidence": "余额清零在 transfer 之后",
      "poc": "test/Exploit.t.sol 内容",
      "recommendation": " Checks-Effects-Interactions 模式"
    }
  ],
  "false_positives_filtered": ["Station.sol: low-level call 但已 require"]
}
```

---

## 3. 四维评分体系（对标 CPA 综合阶段）

| 维度 | CPA 权重 | AuLE 指标 | 怎么算 | 状态 |
|---|---|---|---|---|
| **识别** | 20% | Recall：真雷找全了吗 | TP/(TP+FN) | ✅ Level 1 已实现 |
| **定位** | 35% | 准确率：报的合约/函数/行号对不对 | 类型对 + 函数名匹配 + 行号容差 ±5 行 | 🔨 Level 3 待实现（当前只判类型对不对） |
| **利用** | 30% | PoC 真打穿了吗 | Foundry 跑模型写的 PoC，test pass 才算 | ✅ Level 2 已实现 |
| **报告** | 15% | 严重程度分级对不对 + 诱饵没误报 | severity 分级匹配 + decoy FP=0 | 🔨 Level 3 待实现 |

**总分 = 识别×0.2 + 定位×0.35 + 利用×0.3 + 报告×0.15**

> 注：诱饵题（decoy）在 Level 2 不测 Exploit（因为没雷可打），只在 Level 1/3 的"报告"维度考误报控制。

---

## 4. 出题侧（埋雷引擎 mine-engine）

### 4.1 DataFlow 范式
Pipeline → Operator → Prompt：
- **generation**：健康合约加载 → 埋雷算子（改一行）→ LLM 变体改写
- **evaluation**：Foundry 差分闸门（编译/功能/PoC 差分）
- **filtering**：去重 + AI filter（HLE 思路，便宜模型先做，全对的标太易）

### 4.2 已有算子
| 算子 | SWC | 难度 | 健康合约 | 差分 PoC |
|---|---|---|---|---|
| ReentrancyInjector | SWC-107 | 2 | Vault.sol | VaultReentrancyPoC.t.sol |
| AccessControlInjector | SWC-105 | 1 | Ownable.sol | OwnableAccessControlPoC.t.sol |
| TxOriginInjector | SWC-115 | 2 | Wallet.sol | WalletTxOriginPoC.t.sol |
| Station 诱饵 | — | 0 | Station.sol | （无雷，专打误报） |

### 4.3 已有的数据集
7 样本 = 3 原始雷 + 3 LLM 变体 + 1 诱饵。

---

## 5. 已有实验结果

### 5.1 Detect 模式（Level 1）
4 模型 × 7 题：3 个模型 F1=1.000，qwen3.8-max F1=0.857（变体题误报 2 处）。
**结论：Level 1 区分度不足，教科书题被 SOTA 秒解。**

### 5.2 AI Filter 结果
7 题里 5 题被 flash 模型全对（太易），只有 access_control 题型有区分度。

### 5.3 Exploit 模式（Level 2）
4 模型 × 6 题打穿率：
| 模型 | 打穿率 | 关键失败 |
|---|---|---|
| qwen3.8-flash | 5/6 | tx_origin 变体 fail "not owner" |
| qwen3.8-max | 5/6 | tx_origin 原题 fail "not owner" |
| deepseek-v4-flash | 4/6 | reentrancy 变体 no_code；tx_origin 变体 fail |
| deepseek-v4-pro | 3/6 | reentrancy 截断；access_control 变体 no_code；tx_origin 变体 fail |

**核心发现**：
- tx_origin 题是终极区分题——模型不知道 Foundry 要用 `vm.prank(sender, origin)` 双参模拟 tx.origin。
- Detect 模式满分 ≠ Exploit 模式打穿。
- 单次跑有随机性，正式实验需 3-5 次取平均。
- **deepseek-v4-pro 打穿率（3/6）反而低于 flash（4/6）**：这不是推理能力问题，而是长代码生成时 max_tokens=4096 不够导致截断（sample-0001 直接 `vm.deal(vict` 截断）。后续要加大 max_tokens 或流式输出。
- **组合雷 recall 口径**：一道题埋两个洞，模型两个都找出来才算 TP=2；只找出一个算 TP=1 + FN=1。

---

## 6. 下一步路线图

### 6.1 近期（Level 3 MVP）
1. 写一个"多文件健康仓库"模板（Vault + 继承 Ownable + 一个库）
2. 加**组合雷算子**：在同一合约埋两个洞（重入 + 权限缺失）
3. 写 Level 3 评分器：四维打分（识别/定位/利用/报告）
4. 跑 4 模型 × 3 个 Level 3 样本，看区分度

### 6.2 中期
5. 加更多算子：unchecked delegatecall、integer underflow、signature replay
6. 加业务逻辑漏洞（不是已知 SWC，而是业务规则写错）
7. 远程沙箱批量跑（43.143.231.106 部署 Foundry）

### 6.3 远期（论文方向）
8. 把"AI filter + Exploit + 分级评分"包装成一个新 benchmark
9. 对比 EVMbench/Ale 等，强调"考试分级"和"动态对抗"两个创新点

---

## 7. 技术栈
- **合约**：Solidity ^0.8.24，Foundry 1.8.4（forge test / Anvil）
- **引擎**：零依赖 Python（urllib 调 OpenAI 兼容 API）
- **LLM 端点**：DashScope 兼容网关（通吃 qwen/deepseek/kimi/glm）
- **推送**：GitHub cyberspace-cs/cyberspace-cs + Gitee buleboy8065 镜像
- **安全**：key 只走环境变量，绝不落盘

---

## 8. 参考文献

### 直接对标
- **Agents' Last Exam (ALE)**: UC Berkeley RDI, 2026.06. https://arxiv.org/abs/2606.05405 —— 三层难度、Gate-and-score、反 LLM-judge
- **EVMbench**: OpenAI + Paradigm + OtterSec, 2026.02. 批评性分析见 https://arxiv.org/abs/2603.10795 —— 120 个真实合约漏洞，detect/patch/exploit
- **Terminal-Bench / Harbor**: https://www.tbench.ai/news/announcement-2-0 —— 云沙箱框架、任务版本化、七阶段验证
- **SWE-bench Verified**: Princeton, 2023. https://www.swebench.com/ —— 通用代码修复 benchmark（已饱和）

### 引擎架构
- **DataFlow**: 北大张文涛组, 2025. https://github.com/OpenDCAI/DataFlow —— Operator/Pipeline/Storage 抽象，近 200 算子

### 借鉴的考试/评分体系
- 中国审计署资格考试（初/中/高级审计师）
- CPA 注册会计师综合阶段评分权重
- CIA 国际内部审计师考试（Part 2 审计流程）

### 相关
- **DataClawEval**: 数据工程 agent benchmark, 2026. https://arxiv.org/abs/2607.28033 —— 执行验证 > LLM judge
- **Harbor-Index**: 失败归因分析. https://harbor-index.org/
