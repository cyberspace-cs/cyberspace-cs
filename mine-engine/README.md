# mine-engine · 动态对抗审计考试的埋雷引擎（M0–M3）

把「动态对抗考试 / Adaptive Verifier」落到**智能合约审计**垂直场景的最小可用引擎：
自动在**健康合约**上做一次最小化、可复现的程序变换（埋雷），用**差分 PoC**
证明雷确实是这次埋进去的，再把审计 Agent 的报告对 ground truth 判分。

范式对齐 **OpenDCAI/DataFlow**（https://github.com/OpenDCAI/DataFlow）：
`Pipeline -> Operator -> (Prompt)`，算子处理结构化记录、可串联、可替换后端。

## 闭环

```
健康合约 ──埋雷算子──▶ 埋雷版 + ground truth
                              │
                  差分 PoC（forge test）
   健康版：攻击失败 / 埋雷版：攻击成功 / happy-path 全过
                              │
                  审计报告 ──▶ recall / precision / F1
```

## 目录结构

```
mine-engine/
├─ src/
│  ├─ Vault.sol                 # 健康：资金池（正确 CEI，抗重入）
│  ├─ Ownable.sol               # 健康：访问控制（onlyOwner）
│  ├─ Attacker.sol              # 重入攻击合约（PoC 工具）
│  └─ planted/
│     ├─ VaultPlanted.sol       # 埋雷：重入（SWC-107）黄金输出
│     └─ OwnablePlanted.sol     # 埋雷：访问控制缺失（SWC-105）黄金输出
├─ test/
│  ├─ Vault.t.sol               # Vault 正常功能（4 项）
│  ├─ Ownable.t.sol             # Ownable 正常功能（5 项）
│  ├─ VaultReentrancyPoC.t.sol  # 重入差分 PoC
│  └─ OwnableAccessControlPoC.t.sol  # 访问控制差分 PoC
├─ engine/                      # DataFlow 风格 Python（零第三方依赖）
│  ├─ core/                     # Pipeline/Operator 基类 + Issue schema
│  ├─ generators/               # ArtifactGenerator：加载健康合约
│  ├─ operators/
│  │  ├─ registry.py            # 算子注册中心（核心 IP：按类型动态取用）
│  │  ├─ reentrancy.py          # 重入埋雷（确定性源码变换）
│  │  └─ access_control.py      # 访问控制埋雷（删除身份校验）
│  ├─ validators/               # IssueValidator：forge 差分验证（领域无关）
│  └─ scorers/                  # ReportScorer：报告判分
├─ datasets/                    # 生成样本落盘（clean/planted/meta.json）
└─ run_demo.py                  # 一键演示完整闭环
```

## 运行

需要 [Foundry](https://book.getfoundry.sh/)（forge）。一键演示：

```shell
py run_demo.py
```

单独跑合约测试：

```shell
forge test
```

## M2 实测结果

- **2 个健康合约**（Vault / Ownable）、**2 个埋雷算子**（重入 SWC-107 / 访问控制 SWC-105），
  经**算子注册中心**按类型动态编排；
- 算子生成的埋雷版与黄金版**归一化等价**（忽略注释/空白）；
- `forge test` **13/13 通过**：9 项 happy-path、4 项差分 PoC
  （健康版攻击失败 / 埋雷版攻击成功）；
- 报告判分（ground truth = reentrancy）：

  | 报告策略 | recall | precision | F1 |
  |---|---|---|---|
  | 把所有类型全报一遍（作弊） | 1.0 | 0.083 | 0.154 |
  | 只报确实发现的重入（好审计） | 1.0 | 1.0 | 1.0 |
  | 什么都没发现（漏报） | 0.0 | 1.0 | 0.0 |

  precision 与 recall 同时计分，误报被惩罚，防止「全报一遍」刷分。

## M3 批量生成

```shell
py batch_generate.py
```

- 遍历 `(健康合约 × 埋雷算子)` 组合，逐条做 Foundry 差分验证；
  通过则落盘 `datasets/sample-XXXX/`，失败自动丢弃并记录；
- 产出 `datasets/index.jsonl`（每行一个样本，含 contract/vuln/swc/severity/难度/路径/validated）；
- 当前 2 组合 **差分通过 2/2（有效率 100%）**；
- 固定 seed，两次运行 `index.jsonl` 的 SHA256 完全一致（**可复现**）；
- 新增算子只需在 `registry` 注册并在 `batch_generate.py` 的 `COMBOS` 加一行，即可线性扩充。

## M6 审计 Agent harness + baseline

```powershell
# 密钥走环境变量，仓库不含任何真实 key（.env 已被 .gitignore 排除）
$env:LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:LLM_API_KEY="sk-..."
$env:LLM_MODELS="qwen3.8-flash,deepseek-v4-flash,qwen3.8-max"
py run_benchmark.py
```

- `engine/llm/client.py`：OpenAI 兼容 chat 客户端（urllib 零依赖），base/key/model 全从环境变量读；
- `engine/agents/audit_agent.py`：只喂 planted 源码（不给 clean / PoC / ground truth），要求模型只输出 JSON findings；
- `engine/scorers/report_score.py::score_report`：函数级判分——vuln_type 归一化 + function token 交集，误报计入 FP；
- `run_benchmark.py`：对 index.jsonl 每个样本跑指定模型，输出 TP/FP/FN/Recall/Precision/F1 汇总表。

**baseline 实测（4 样本：3 雷 reentrancy/access_control/tx_origin + 1 诱饵 Station，DashScope 网关）**：

| model | TP | FP | FN | Recall | Precision | F1 |
|---|---|---|---|---|---|---|
| qwen3.8-flash | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| deepseek-v4-flash | 2 | 2 | 1 | 0.667 | 0.500 | 0.571 |
| qwen3.8-max | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |

**benchmark 首次拉开差距**：deepseek-v4-flash 在 access_control 题上既漏报（没认出 onlyOwner 校验被删）又误报（多报 2 处），F1 掉到 0.571；qwen 系全满分。诱饵题（Station：low-level call 但已 require 检查）三模型均未误报——说明这题对当前 SOTA 仍偏易，但 access_control 的"空 modifier"陷阱已能区分模型。

## 下一步（M7+）

- **继续加难**：unchecked call（SWC-104）、组合雷（同合约多雷）、更隐蔽的诱饵；
  让 qwen 系也开始丢分；
- 多轮工具调用 Agent（读文件 / grep / forge test）替代单轮；
- 远程沙箱（ubuntu@43.143.231.106，已测 SSH 通）部署 Foundry + harness，做批量/受控评测；
- 位置/证据级匹配，替代当前的类型集合匹配；
- 埋雷–审计共演化；金融账套 adapter（共享同一套四组件接口）。
