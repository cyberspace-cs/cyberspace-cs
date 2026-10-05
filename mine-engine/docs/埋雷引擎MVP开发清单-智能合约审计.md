# 注入漏洞引擎 MVP・可执行开发清单

> 首个落地领域：
>
> **智能合约代码审计（Solidity / EVM）**
> 目标：用最小工作量，跑通注入漏洞引擎的完整闭环，并把引擎核心做成
>
> **领域无关**
>
> ，为金融账套审计预留接口。



***

## 0. 为什么先做智能合约，而不是金融账套



| 维度 | 智能合约（先做） | 金融账套（第二个 adapter） |
| --------- | ----------------------------------- | ------------------------------- |
| 种子程序生成 | 合约短小自包含，OpenZeppelin / Foundry 模板现成 | 需先做 "自洽账套生成器"（借贷平衡 + 勾稽关系），工程量大 |
| 漏洞 / 造假模式 | SWC 分类明确、单文件可注入 | 虚增一笔收入要联动改应收 / 税费 / 现金流，否则一眼假 |
| 雷是否真的存在 | 跑 PoC 攻击测试即可程序化证明 | 较难完全自动判定 "埋得真不真" |
| 判分客观性 | 高（链上状态 + 测试） | 中（需更多规则 / 人工抽检） |

**核心策略**：引擎抽象出 4 个领域无关组件，合约是第一个实现；跑通后金融账套只需替换这 4 个组件。



```
ArtifactGenerator 生成“种子程序”
IssueOperator 注入漏洞（注入问题）
IssueValidator 差分验证“雷确实存在、且没搞坏材料”
ReportScorer 审计报告对 ground truth 判分
```



***

## 1. MVP 范围与完成定义（先约定，防止越做越大）

**做**



* 种子合约 ≥ 5 个；漏洞类型 ≥ 8 类

* 自动生成 **≥ 50 个 “差分验证通过” 的带雷样本**

* 审计 Agent 端到端跑通，自动输出 **召回率 / 精确率 / F1 / 定位准确率**

* 跑 ≥ 2 个前沿模型作 baseline，结果可复现

* 4 个引擎组件领域无关、接口稳定

**不做（留给后续）**



* 完整审计工作流与过程评分（先只做结果判分）

* 金融账套领域、RL 训练、self-play 共演化（仅预留接口）

* 追求与 EVMbench 比规模

**MVP 完成的硬标准（DoD）**



* [ ] 一条命令从 0 生成数据集（种子程序→注入漏洞→验证→落盘）

* [ ] 一条命令跑审计 Agent 并出排行榜

* [ ] 样本 100% 经过差分验证；删掉验证步骤后分数明显变化（证明验证有效）

* [ ] 重跑两次，各模型分数差异在可接受噪声内（可复现）



***

## 2. 技术栈与环境（M0）



* [ ] 安装 Foundry：`curl -L https://foundry.paradigm.xyz | bash` → `foundryup`

* [ ] 验证：`forge --version`、`anvil --version`

* [ ] 安装静态分析 Slither：`pip install slither-analyzer`（需 Python 3.9+）

* [ ] Python 编排环境：`pip install pydantic jsonschema`（数据校验）

* [ ] LLM 调用：统一封装一个 `llm_client`（支持切换模型、记录原始输出便于复现）

* [ ] 初始化仓库并跑通示例：`forge init hello && cd hello && forge test`

**推荐目录结构**



```
mine-engine/
├─ engine/
│ ├─ core/ # pipeline 编排、数据 schema、随机种子
│ ├─ generators/ # ArtifactGenerator：contracts/（合约）、ledger/（金融，预留）
│ ├─ operators/ # IssueOperator：每类漏洞一个算子
│ ├─ validators/ # IssueValidator：差分验证
│ └─ scorers/ # ReportScorer：报告匹配与指标
├─ corpus/
│ ├─ clean/ # 种子合约源码
│ └─ templates/ # 每类漏洞的 PoC 攻击测试模板
├─ datasets/
│ └─ sample-XXXX/ # clean/ planted/ poc/ meta.json
├─ agents/ # 审计 Agent harness（工具 + 报告格式）
└─ harbor/ # Harbor 封装（M7，可选）
```

**验收**：示例项目 `forge test` 全绿；目录骨架建好。



***

## 3. 模块拆解与任务

### M1・种子合约库（ArtifactGenerator・合约）



* [ ] 选定 5–8 类高频、结构典型的合约：


 * [ ] ERC20 代币

 * [ ] Vault / 资金池（存取代记）

 * [ ] Escrow 托管

 * [ ] Auction 拍卖

 * [ ] Staking 质押

 * [ ] Multi-sig 多签钱包

 * [ ] AMM 交易对（可选，较复杂）

 * [ ] Ownable 权限合约

* [ ] 每个合约产出：


 * [ ] 干净、规范的实现（参考 OpenZeppelin Contracts，自己写**简化但完整**的版本，避免直接拷贝造成版权 / 污染问题）

 * [ ] 完整 happy-path 功能测试（正常存取、正常竞拍成交等）

 * [ ] 编译零警告；`slither` 无高危

* [ ] 记录每个合约的 “正常功能基线”（哪些测试必须始终通过）

**验收**：所有种子合约 `forge build` 通过、功能测试全绿、Slither 无高危。

> 关键原则：种子程序必须
>
> **先证明自己是健康的**
>
> ，否则后面无法做差分。



***

### M2・漏洞算子库 + PoC 模板（IssueOperator，核心 IP）

选定 8–10 类高频漏洞，每类交付三样东西：**注入算子 + PoC 攻击测试模板 + 标注模板**。



* [ ] **重入 Reentrancy（SWC-107）**

- 算子：把 “余额清零 / 状态更新” 从外部 call 之前挪到之后（破坏 Checks-Effects-Interactions）

* [ ] **未检查外部调用返回值（SWC-104）**

- 算子：删除 low-level call 的成功判断

* [ ] **tx.origin 鉴权（SWC-115）**

- 算子：把 `msg.sender == owner` 改成 `tx.origin == owner`

* [ ] **访问控制缺失（SWC-105）**

- 算子：去掉 `onlyOwner` / 把敏感函数设为 public

* [ ] **不安全的 delegatecall（SWC-112）**

- 算子：引入对可控地址的 delegatecall

* [ ] **整数精度 / 取整错误**

- 算子：调换乘除顺序、错误的手续费计算

* [ ] **拒绝服务（路径 / 收款方阻塞）**

- 算子：强制向固定地址转账、循环依赖外部状态

* [ ] **签名重放 Signature Replay**

- 算子：去掉 nonce /chainId 校验

* [ ] **错误的 ERC20 用法（transfer 不检查）**

* [ ] **逻辑后门（可选，LLM 注入更自然）**：如特定地址免手续费 / 可自毁

**每类算子的两种实现方式**



* [ ] **确定性算子（优先）**：基于源码模式匹配或简单 AST 变换，结果可复现

* [ ] **LLM 注入（补充）**：给定漏洞类型与代码，让 LLM 改写出 “看起来自然” 的漏洞（用于生成不重复、更隐蔽的变体）

**PoC 模板要求**



* [ ] PoC 是一个攻击测试：部署合约 → 执行攻击 → 断言 “攻击收益成立”

* [ ] 同一个 PoC 必须能区分 clean /planted（见 M4）

**验收**：每类算子在 ≥1 个样例上手工验证可触发；PoC 在 planted 上成功、clean 上失败。



***

### M3・注入漏洞引擎编排（core pipeline）



* [ ] 输入参数：`clean_id`、`vuln_types[]`、`difficulty`、`num_issues`（单雷 / 多雷）、`seed`

* [ ] 流程：

1. 复制种子合约到工作目录

2. 调用对应算子（确定性优先，失败再用 LLM）

3. 调用 M4 差分验证

4. 验证通过 → 生成 `meta.json` 并落盘；失败 → 记录原因、按预算重试或丢弃

* [ ] 支持批量生成与进度统计（成功率、各漏洞类型分布）

* [ ] 多雷组合：注入多个不同类型的雷，分别验证

* [ ] 固定随机种子，保证可复现

**验收**：一条命令批量生成 K 个样本，输出有效率报告；相同种子重跑结果一致。



***

### M4・差分验证器（IssueValidator，质量闸门）

对每个候选 planted 样本，**全部**满足才算有效：



* [ ] `forge build` 编译通过

* [ ] 所有 happy-path 功能测试仍通过（注入漏洞**不能破坏正常功能**，否则太假）

* [ ] **PoC 在 planted 上攻击成功**（断言通过）

* [ ] **PoC 在 clean 上攻击失败**（断言不成立 /revert/ 资金未被盗）

* [ ] （多雷时）每个雷都有各自 PoC 独立验证

**为什么必须 “差分”**：



* 只有 planted 成功、clean 失败同时成立，才证明 “雷是这次埋进去的、且确实可被利用”；

* 自动过滤三类废品：注入漏洞没成功、把合约改坏、PoC 本身写错。

**验收**：故意构造的 “坏样本”（编译失败 / 雷没触发 / 破坏功能）能被 100% 拒绝。



***

### M5・Ground Truth Schema 与数据集存储



* [ ] 定义 issue 标注 schema（建议用 pydantic + JSON Schema 校验）：



```
{
 "issue_id": "sample-0007__01",
 "sample_id": "sample-0007",
 "vuln_type": "reentrancy",
 "swc": "SWC-107",
 "severity": "high",
 "location": {
 "file": "src/Vault.sol",
 "function": "withdraw",
 "start_line": 42,
 "end_line": 49
 },
 "difficulty": 2,
 "poc": "test/PoC.t.sol",
 "discovery_hint": "外部调用前未更新状态",
 "operator": "reentrancy_swap_order",
 "seed": 20260928
}
```



* [ ] 每个样本目录固定结构：`clean/`、`planted/`、`poc/`、`meta.json`

* [ ] 数据集清单 `index.jsonl`（每行一个样本，便于切片 / 去重）

**验收**：所有样本通过 schema 校验；scorer 能仅凭 `index.jsonl` 加载全部 ground truth。



***

### M6・审计 Agent Harness + 自动判分（ReportScorer）

**Agent harness**



* [ ] 给 Agent 提供最小工具集：读文件、列目录、grep、`forge test`、`slither`

* [ ] Agent 只拿到 `planted/`（**不给** clean、poc、meta），任务：审计并产出标准化报告

* [ ] 报告格式（JSON）：每个发现含 `vuln_type / file / function / line / severity / evidence`

* [ ] 记录完整轨迹（读了哪些文件、跑了哪些命令），为后续 “过程分” 留数据

**判分逻辑**



* [ ] 匹配规则：一个 ground-truth 雷被 “类型正确 + 位置命中”（函数级，或行级 ±N 容差）算作 TP

* [ ] 统计 TP / FP / FN，输出：


 * [ ] **Bug-level 召回率 Recall**（找全没）

 * [ ] **精确率 Precision**（乱报罚，防止 “把所有类型报一遍”）

 * [ ] **F1**

 * [ ] 严重度加权 Recall/F1

 * [ ] 定位准确率（函数级 / 行级）

* [ ] Baseline：跑 ≥2 个前沿模型 + 一个 “朴素规则 / 全报” 对照（验证指标不会被刷）

**验收**：端到端跑通并输出可复现排行榜；“全报一遍” 的对照因 Precision 极低而 F1 很低（证明抗 game）。



***

### M7・Harbor 封装（可选，建议在 M6 跑通后做）



* [ ] 制作内置 Foundry 的沙箱镜像

* [ ] 把样本与 scorer 封装为 Harbor dataset /task（输入 planted，输出报告与分数）

* [ ] 复用 Harbor 的 task /trial/job 模型批量跑 baseline

* [ ] （可选）参考 Harbor Index 的筛选流程做样本蒸馏

**验收**：`harbor run` 能跑通单题并返回分数。



***

## 4. 里程碑（全职参考，可按实际节奏拉长）



| 时间 | 交付 |
| ----- | ------------------------------------- |
| 第 1 周 | M0 环境 + M1 种子合约库 |
| 第 2 周 | M2 漏洞算子 + PoC 模板（先做最高频 5 类） |
| 第 3 周 | M3 编排 + M4 差分验证 + M5 schema |
| 第 4 周 | M6 Agent + 判分 + baseline（+ M7 Harbor） |

> 建议顺序：
>
> **M2 先只做 5 类最高频漏洞**
>
> ，端到端跑通 M3–M6 拿到第一版分数，再回头补齐漏洞类型 —— 先闭环，再丰富。



***

## 5. 主要风险与应对



| 风险 | 应对 |
| -------------------------- | ----------------------------------------------------------------- |
| LLM 注入漏洞编译失败率高、不稳定 | 以确定性算子为主、LLM 兜底；M4 差分验证强制把关 |
| PoC 模板编写耗时 | 先覆盖重入等最高频 5 类，其余迭代补 |
| 题目过易（grep 即见）或过难 | 用 difficulty 分层并统计各档命中率；过难 / 过易的类型后续交给共演化调节 |
| 与 EVMbench / BlockBench 撞车 | 差异化放在 “**可无限生成的引擎 + 后续工作流 / 过程评估 + 注入漏洞共演化**”，MVP 不比规模、比 “可生成性与抗污染” |
| 分数有随机性 | 固定种子、多次运行取均值、报告置信区间 |



***

## 6. MVP 之后的三步延展



1. **金融账套 adapter**：实现 `generators/ledger/`（自洽账套生成器）与对应造假算子、勾稽差分验证，复用其余引擎代码。

2. **注入漏洞–审计 self-play 共演化**：审计 Agent 变强后，注入漏洞方自动生成更隐蔽的雷，维持难度自适应（落地 Adaptive Verifier 主线）。

3. **完整审计工作流 + 过程分**：强制走 “计划→风险评估→控制测试→实质性程序→汇总→报告→复核”，增加审计程序覆盖率、底稿完整度、证据充分性等过程指标。



***

## 7. 一页速查（开工时贴墙上）



* 种子程序先自证健康（编译 + 功能测试 + Slither）

* 每个雷 = 算子 + PoC + 标注三件套

* 差分验证：clean 上攻击失败、planted 上攻击成功，缺一不可

* 判分同时看 Recall 和 Precision，乱报必罚

* 先 5 类漏洞端到端闭环，再扩类型、再上 Harbor、再做金融