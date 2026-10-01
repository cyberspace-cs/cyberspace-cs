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

**baseline 实测（7 样本：3 雷×{原题,LLM变体} + 1 诱饵，DashScope 网关，standard prompt）**：

| model | TP | FP | FN | Recall | Precision | F1 |
|---|---|---|---|---|---|---|
| qwen3.8-flash | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| deepseek-v4-flash | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| deepseek-v4-pro | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| qwen3.8-max | 6 | 2 | 0 | 1.000 | 0.750 | 0.857 |

**发现**：① deepseek-v4-pro（官方真实模型名，V4-Pro-0813）满分；② 上次 deepseek-v4-flash 翻车这次满分，说明单次跑有随机性，baseline 需多次取平均；③ LLM 变体题让 qwen3.8-max 误报 2 处（precision 0.75）——改写后的代码让大模型过度敏感。区分度刚起步，题还要继续加难。

## M7 · 抗污染、可复现、接入行业标准

定位升级：**mine-engine 不是审计 Agent，是"会自己出题的考试院"**——
一台持续产出**新鲜、可验证、抗污染**审计考题的引擎。智能合约是它落地的第一个赛道。

为什么必须是"引擎"而不是"数据集"：公开 benchmark 一发布就开始腐烂（题目泄漏进训练语料）。
EVMbench 用训练截止后的真实事故做无污染重测，Agent 表现断崖下跌——这就是证据。
我们的题是**考试开始那一刻才生成**的，背不到。

### Harbor 导出（对齐行业标准）

[Harbor](https://github.com/harbor-framework/harbor) 是 Terminal-Bench 团队出品的评测执行器，
正在成为跑分的事实标准。一键把数据集导出成它的任务三元组：

```shell
py run_harbor_export.py                    # 默认 detect 模式 -> harbor_tasks/
py run_harbor_export.py --mode exploit     # 判攻击 PoC 能否真打穿

uv tool install harbor
harbor run --dataset-path harbor_tasks --agent claude-code --model anthropic/claude-opus-4-1
```

每个任务目录严格遵循 `instruction.md + environment/ + tests/ + solution/`：
**ground truth 只存在于 `tests/` 下**，agent 在 workspace 里翻不到答案。

### 判分 v2（类型 + 定位 IoU + 严重度加权）

```shell
py run_benchmark.py --scorer v2 --repeat 5 --out results.json
```

| 场景 | v1（旧） | v2（新） |
|---|---|---|
| 说 "non-reentrant"（意为安全）却填 reentrancy | ❌ 误判为 TP | ✅ 判为 FP（否定词检测） |
| 定位到错误的函数 | 只按类型判，仍算 TP | 定位分扣减，F1 下降到 0.82 |
| 把 critical 报成 low | 不扣分 | recall 扣到 0.8 |
| 同一雷重复报两次 | 重复计数 | 自动去重 |
| 定位粒度 | — | 遵循"判分严格度不超过标注粒度"：gt 是函数级区间时，报区间内任意行即算命中 |

### 难度 / 区分度 / 抗污染（engine/analytics）

| 指标 | 含义 |
|---|---|
| `item_difficulty` | 实测难度（替代此前手填的 1/2） |
| `item_discrimination` | 区分度 D = 高能力组通过率 − 低能力组通过率，>0.3 为好题 |
| `fit_rasch` | 简化 IRT（1PL）拟合，把题目难度与模型能力放到同一把尺子上 |
| `contamination_resistance` | **CRS 抗污染分**：同算子换 seed 重生成新题后分数是否稳定 |

CRS 只有"引擎型"benchmark 能算，静态数据集算不了——这是我们的结构性优势。

### 三条赛道（四组件领域无关，换 adapter 即可）

| 赛道 | 验证器硬度 | 状态 |
|---|---|---|
| 智能合约审计 | L1 · 编译器 + 测试 | ✅ 已落地 |
| 企业审计（舞弊/内控） | L2 · 三表勾稽 + 凭证链 | 设计完成（8 个算子） |
| 国家审计（财政资金） | L3 · 勾稽 + 法条命中 | 设计完成（8 个算子） |
| 审计师（CPA 底稿） | L4 · 持牌人 rubric | 设计完成（7 个算子） |

```shell
py -c "from engine.adapters import list_domains, scaffold_checklist; \
print([d.name_cn for d in list_domains()]); print(scaffold_checklist('corp-audit'))"
```

## 研究文档

完整分析见 [`docs/`](./docs)：

| 文档 | 内容 |
| --- | --- |
| [00-INDEX](./docs/00-INDEX.md) | 索引与三分钟速读 |
| [01-code-review](./docs/01-code-review.md) | 代码与资产现状审查（含 P0/P1 问题清单） |
| [02-evolution](./docs/02-evolution.md) | 研究演进脉络（新手向，从"人出题"到"机器出题"） |
| [03-landscape](./docs/03-landscape.md) | 同行 benchmark 全景与定位矩阵 |
| [04-three-tracks](./docs/04-three-tracks.md) | 国家审计 / 企业审计 / 审计师三条赛道的数据设计 |
| [05-ideas](./docs/05-ideas.md) | 7 个科研 idea（含创新性/工作量/风险评分） |
| [06-roadmap](./docs/06-roadmap.md) | M7–M10 工程路线图 |

可视化报告：[`docs/report.html`](./docs/report.html)

## 下一步（M8+）

- **继续加难**：unchecked call（SWC-104）、组合雷（同合约多雷）、更隐蔽的诱饵；
  让 qwen 系也开始丢分；
- **Review 模式**：给模型一份"已完成的审计报告"，里面埋了错误结论，让它复核
  （借鉴 FinancialAuditBench 的 review 设定，成本更低、区分度更高）；
- 多轮工具调用 Agent（读文件 / grep / forge test）替代单轮；
- 远程沙箱部署 Foundry + harness，做批量/受控评测；
- **第二个 adapter**：优先企业审计（验证器最硬、数据最公开），证明四组件抽象真的跨赛道；
- 埋雷–审计共演化。
