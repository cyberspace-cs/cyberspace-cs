# AuLE 代码实现方案 v0.2
## 借鉴 DataFlow 架构重构 mine-engine

> **DataFlow**（北大 OpenDCAI / 张文涛组，arXiv:**2512.16676**）
> 核心抽象：Operator / Storage / LLMServing / PromptABC / PipelineABC。
> 我们轻量借鉴，不引入 pandas 重依赖，用 JSONL 当 Storage。

---

## ⚠️ 先看这一页：v0.1 写了五项计划，现在做成什么样了

v0.1 最大的毛病是**没标完成状态**——读起来像一份全新计划，
看不出哪些已经做了。这一版先补上这个对照。

| v0.1 的第 N 步 | 计划内容 | 状态 | 实际落在哪 |
|---|---|---|---|
| 1 | core 层（operator/storage/serving/prompt/registry）1 天 | 🟡 **部分完成** | Operator/Pipeline + 四组件抽象**已落地**，但全在 `engine/core/pipeline.py` 一个文件里；<br>storage / serving / prompt **三个都没做**；registry 实际在 `engine/operators/registry.py` |
| 2 | 迁移现有算子到 OperatorABC　0.5 天 | ✅ **已完成** | 四个算子全部继承 `IssueOperator`：<br>`ReentrancyInjector` `AccessControlInjector` `TxOriginInjector` `VariationOperator` |
| 3 | 写三个 Pipeline 类替换手写脚本　1 天 | ❌ **没做** | 仍然是 5 个顶层脚本（见第 4 章，**这个决定是对的**，下面解释） |
| 4 | 加业务逻辑算子 `business_logic.py`　0.5 天 | ❌ **没做** | — |
| 5 | 跑 baseline 验证　0.5 天 | 🟡 **部分完成** | Level 1 跑过（3 模型 F1 全 1.000）；<br>Level 2 跑过（打穿率 50–83%）；**但埋雷成功率基线没跑过** |

> **一句话**：v0.1 里**最有价值的那部分（统一算子抽象）已经做完了**，
> 剩下的是三件"形式统一"的工作。所以这一版**不再把重构当主线**——
> 主线是 [`10-action-plan`](./10-action-plan.md) 的四步走，理由见第 6 章。

---

## 1. DataFlow 借鉴点（补出处，标注落地状态）

| DataFlow 概念 | 它怎么做 | 我们怎么借鉴 | 落地 |
|---|---|---|---|
| OperatorABC | `__init__` + `run(storage, input_*_key, output_*_key)` + `get_desc()` | 统一算子基类，所有埋雷/评分/过滤算子继承 | ✅ 已落地为 `core.pipeline.Operator` |
| FileStorage | pandas DataFrame，每步缓存 jsonl，支持 resume_step | 用 list[dict] + JSONL 文件缓存，每步落盘 | ❌ 未做 |
| LLMServing | 算子不自己 new LLM，构造函数注入 | LLMClient 注入到需要 LLM 的算子 | ✅ `VariationOperator(client=...)` 已是注入式 |
| PromptABC | Prompt 独立成类，`@PROMPT_REGISTRY.register()` | Prompt 模板类化，注册到全局 REGISTRY | ❌ 未做（prompt 是 agent 里的字典） |
| prompt_restrict | 算子声明允许哪些 Prompt | 暂不做类型检查 | ➖ 主动不做 |
| PipelineABC | `__init__` 定义算子，`forward()` 串联 | 每个评测流程一个 Pipeline 类 | 🟡 基类有，但流程是脚本不是类 |
| compile() + resume_step | DAG 预编译，从断点恢复 | 每步检查缓存文件存在就跳过 | ❌ 未做 |
| draw_graph() | 可视化 DAG | 暂不做 | ➖ 主动不做 |

**实际代码长这样**（`engine/core/pipeline.py`，不是编的）：

```python
class Operator:
    name = "operator"
    def __init__(self, **config):
        for key, value in config.items():
            setattr(self, key, value)
    def run(self, records): raise NotImplementedError

class Pipeline:
    def run(self, records):
        for operator in self.operators:
            records = operator.run(records)
        return list(records)

# 四个领域无关组件抽象 —— 换赛道时实现这四个即可
class ArtifactGenerator(Operator): ...   # 造健康材料
class IssueOperator(Operator): ...       # 埋雷 + 产出 ground truth
class IssueValidator(Operator): ...      # 差分验证
class ReportScorer(Operator): ...        # 判分
```

对比原方案（`run(storage, input_key, output_key)`）：
**我们没用 storage 参数，直接用 `records` 列表传进传出。**
这是有意简化——DataFlow 用 storage 是为了让算子之间能按 key 随机访问，
而我们的算子是**严格单向流水线**（埋雷 → 验证 → 判分），
列表传递就够了，多一层 storage 反而增加理解成本。

---

## 2. 目录结构：现状 vs 目标

图例：✅ 已有 ｜ ❌ 缺 ｜ 🔄 位置与 v0.1 计划不同 ｜ ➖ 主动不做

```
mine-engine/
├── engine/
│   ├── core/
│   │   ├── pipeline.py       ✅ Operator / Pipeline / 四组件抽象（v0.1 计划的 operator.py 在此合并）
│   │   ├── schema.py         ✅ Issue / Location 数据结构
│   │   ├── operator.py       ❌ 未单独拆出（目前合在 pipeline.py，够用）
│   │   ├── storage.py        ❌ 未做 —— 扩到 50+ 题时才需要
│   │   ├── serving.py        ❌ 未做 —— 仅有 engine/llm/client.py
│   │   └── prompt.py         ❌ 未做 —— prompt 是 agent 内的字典
│   ├── operators/
│   │   ├── reentrancy.py     ✅ 继承 IssueOperator
│   │   ├── access_control.py ✅
│   │   ├── tx_origin.py      ✅
│   │   ├── variation.py      ✅ LLM 变体改写（已有 k 参数，参数化雏形）
│   │   ├── business_logic.py ❌ 未做 —— 业务逻辑雷（利息算错）
│   │   └── registry.py       🔄 在 operators/ 而非计划中的 core/
│   ├── prompts/              ❌ 未做
│   ├── agents/               ✅ audit / exploit / level3 三个都在
│   ├── scorers/              ✅ report_score / level3_score
│   ├── validators/           ✅ foundry_diff / dedup
│   ├── adapters/             ✅ 本次新增：harbor 导出 + 三条赛道契约
│   ├── analytics/            ✅ 本次新增：difficulty / env_quality / openended
│   └── llm/client.py         🔄 计划中没有，实际在这里
├── pipelines/                ❌ 未做 —— 见第 4 章，改为 5 个顶层脚本
├── run_*.py                  ✅ 见下
└── datasets/                 ✅ 生成的样本
```

**为什么说 registry 放 `operators/` 是对的**：
它注册的是"埋雷算子"（含 swc 编号、默认难度、作用哪个健康合约），
跟这些算子放一起比放 core 里更好找。v0.1 计划的位置不必追。

### 顶层脚本（v0.1 写的 `run_level1.py` / `run_level2.py` 不存在）

| 实际脚本 | 干什么 |
|---|---|
| `batch_generate.py` | 批量埋雷 + 差分验证，落盘 datasets/ |
| `run_ai_filter.py` | 便宜模型先做一遍，筛掉太简单/有问题的题 |
| `run_benchmark.py` | Level 1 正式考试 + 判分（支持 `--repeat N`） |
| `run_exploit.py` | Level 2 让模型写 PoC 并真跑 |
| `run_level3.py` | Level 3 多文件仓库端到端审计 |
| `run_harbor_export.py` | 导出成 Harbor 任务三元组 |
| `run_env_quality.py` | 环境四维体检 |

---

## 3. 核心接口：方案写的 vs 实际写的

### 3.1 Operator

**v0.1 计划**：`run(self, storage, **keys)`，靠 storage 管理数据。
**实际**：`run(self, records)`，靠列表传进传出（理由见第 1 章）。

```python
class Operator:
    name = "operator"
    def __init__(self, **config):      # v0.1 写 self.kwargs = kwargs，
        for k, v in config.items():    # 实际是 setattr，好处是算子内可直接 self.k / self.seed
            setattr(self, k, v)
```

> 这个改动是**有意的**，不是实现偏差：写成 `self.seed` 比 `self.kwargs["seed"]`
> 可读性好得多，而且第四步的"难度旋钮"要往算子传一堆参数，这样更顺手。

### 3.2 Storage　❌ 未做

v0.1 的设计（保留，未实现）：

```python
class JSONLStorage:
    def __init__(self, path, cache_dir="./cache"): ...
    def write(self, step_name, records): ...   # 每步落盘，支持 resume
```

### 3.3 Pipeline　🟡 基类有，流程是脚本

```python
class Pipeline:
    def run(self, records):
        for operator in self.operators:
            records = operator.run(records)
        return list(records)
```

### 3.4 LLM 客户端　🔄 计划外，但现在是关键缺口

```python
# engine/llm/client.py —— 当前实现（简化）
return data["choices"][0]["message"]["content"]
```

✅ **`usage` 透传已实现**（2026-10-02）：`engine/llm/client.py` 的 `chat_detailed()`
现在把 API 返回的 `usage`（输入/输出 token、cache、reasoning）一并带出，成本已能算
（见 [`10-action-plan`](./10-action-plan.md) 第 3.1 节 / [doc 12](./12-真实模型接入与踩坑记.md)）。
这原本是实打实的功能缺口，现已补上。

---

## 4. 三个 Pipeline 实际拆成了五个脚本——为什么这是对的

v0.1 画的 Level 1 是一条长流水线：

```
健康合约 → 三个 Injector → Variation → FoundryDiff → DedupFilter
→ AIFilter → AuditAgent → ReportScorer
```

实际拆成了三段：`batch_generate.py` → `run_ai_filter.py` → `run_benchmark.py`。

**拆分是对的，别再合并回去**，三个理由：

1. **成本**：埋雷 + 差分验证要跑 `forge test`，很慢；判分要调 LLM，要钱。
   合成一条流水线，每次调 prompt 都得重跑埋雷。
2. **可检查**：中间产物（datasets/sample-*/）能直接打开看，
   出问题知道卡在哪一步。合成一条流水线只能看到最终分数。
3. **可缓存**：题目生成一次，可以拿去考很多个模型。
   这是 benchmark 引擎的本职工作——**题和考试本来就该分开**。

> 一句话：**出题是一次性的，考试是反复的。** 分开才对。

各 Pipeline 的实际形态：

| Pipeline | 实际 |
|---|---|
| Level 1 Detect | `batch_generate` → `run_ai_filter` → `run_benchmark` |
| Level 2 Exploit | `run_exploit`（写 PoC → forge 编译 → 跑，分 success/fail/compile_fail/no_code） |
| Level 3 Audit | `run_level3`（多文件仓库 → 端到端审计 → 四维打分） |

⚠️ 另有一处过时表述：v0.1 写"AuditAgent(**4 模型**)"。
实际模型是**环境变量配置**，不写死数量：

```bash
$env:LLM_MODELS="deepseek-flash,deepseek-v4-pro"
```
> ⚠️ 模型名以网关实际为准：DeepSeek 官方网关只有 `deepseek-flash` / `deepseek-v4-pro`，
> `deepseek-v4-flash` 会被**静默改名**为 `deepseek-flash`（见 [doc 12](./12-真实模型接入与踩坑记.md) 第 1 节）。
> DashScope 上的名字是另一套（`qwen3.8-flash` / `qwen3.8-max` 等，但账户欠费暂不可用）。

---

## 5. 修订后的实施顺序（剩余工作）

v0.1 的五步里，**第 2 步已完成、第 1 步大部分已完成**。
下面只列**真正还没做的**，按"收益 ÷ 工作量"排序，每条带**可执行的验收标准**。

### S1 · 给 LLM 客户端补 usage 透传　✅ 已完成（2026-10-02）

> ✅ **状态：已完成。** `chat_detailed()` 已返回 `Usage(tokens_in/out)`，`run_benchmark.py`
> 接入成本记账，真实跑测见 [doc 12](./12-真实模型接入与踩坑记.md)。原"最急"项已消除，
> 故从"待做"移入"已完成"。下面保留原设计说明供追溯。

**做什么**：`engine/llm/client.py` 的 `chat()` 除了返回文本，还要返回 token 用量。

**为什么最急**：[`10-action-plan`](./10-action-plan.md) 第一步（记时间和钱）**卡在这上面**——
没有 token 数，成本算不出来。它名义上属于 DataFlow 的 LLMServing，
但**不必先建 serving 抽象**，直接改 client 更快。

两个真实坑：
- 各供应商字段名不一致（OpenAI 系 `prompt_tokens`/`completion_tokens`，
  有的厂商叫 `input_tokens`/`output_tokens`），要都认
- 单价表要能配置，不能写死在代码里

**验收**：跑一次 `run_benchmark.py`，结果文件里每个模型都有
`tokens_in` / `tokens_out` / `cost_usd`，**且不能全是 0 或 null**。

---

### S2 · 加业务逻辑算子 `business_logic.py`　⏱ 1 天　🥈

**做什么**：第五个埋雷算子，埋"业务逻辑错误"（比如利息算错一位小数）。

**为什么**：环境四维体检实测**多样性只有 0.3665**，诊断是
"类别均衡 0.975 很高，但**结构离散只有 0.173**——雷型分散，代码同质"。
现有四个算子三个是"把某一行挪位置"式的变换，加一个**算错数**的算子，
结构上就多了一类。

⚠️ **优先级有过冲突**：[前沿调研报告](./AuLE-前沿调研报告.md) 第 4.1 节把它列为 **P0**
（理由是"这是我们和 EVMbench 最大的差异"），v0.1 却排在第 4 步。
**本版裁决：排在四步走之后**。理由——它是"加题"，而当前第一问题是
"现有的题都考满分、区分度为零"。**先让卷子有区分度，再往卷子里加题。**

**验收**：新算子埋的雷能通过差分验证（健康版 PoC 打不穿、埋雷版打得穿），
且 `run_env_quality.py` 的**结构离散度上升**（记下前后数字对比）。

---

### S3 · JSONLStorage + resume　⏱ 1 天　🥉 扩题时才做

**做什么**：每步落盘 jsonl，重跑时跳过已完成的步骤。

**为什么排第三**：现在只有 4 道独立题（`datasets/sample-*`，其中 3 个是 `-v1` 变体），
一次跑几分钟，断点续跑没意义。**等扩到 50–100 题时它才变成刚需**。

**验收**：人为在中间一步 kill 掉，重跑时**不重复已完成步骤**，且结果一致。

---

### S4 · Prompt 模板化（PROMPT_REGISTRY）　⏱ 1 天　➖ 建议不做

**做什么**：把散在各 agent 里的 prompt 字典抽成类，注册到全局。

**为什么建议不做**：现有 prompt 一共 4 处（见
[00-INDEX](./00-INDEX.md) 末节），都在自己的 agent 里，改起来很方便。
抽成注册中心后，**改一句 prompt 要跳两个文件**，收益是"看起来更规整"。

> DataFlow 需要它，是因为它有**近 200 个算子**共用 prompt 模板。
> 我们有 4 个。**规模没到，别上框架。**

---

## 6. 与 10-action-plan 的关系（裁决冲突）

三份文档对"要不要重构"说法不一致，这里是最终裁决：

| 文档 | 说法 |
|---|---|
| 本方案 v0.1 | 重构 core 层是**第 1 步**，1.5 天 |
| [前沿调研报告](./AuLE-前沿调研报告.md) 4.1 | 迁移是 **P1**，"不阻塞实验" |
| [10-action-plan](./10-action-plan.md) 第 6 章 | **不推倒重写**引擎 |

**裁决：10-action-plan 是对的，本方案的重构降级为支线。**

理由：**v0.1 真正有价值的那一半（统一算子抽象）已经落地了**，
剩下的三件（storage / serving / prompt）里，只有 serving 有实际功能缺口
（且不必做成抽象，直接改 client），另两件是形式统一。
**为了形式统一去动一个正在出结果的引擎，不划算。**

所以：

```
主线（10-action-plan 四步走，约 4 天）
  ① 记时间与钱   ← 依赖本方案 S1
  ② 防伪检查（白卷 / 标准答案 / 反向白卷）
  ③ 题坏了喂回去修（自我修正循环）
  ④ 难度连续旋钮
支线（本文档 S2–S4）：主线跑完、或需要扩题时再做
```

---

## 7. 明确不做

| 不做 | 为什么 |
|---|---|
| `draw_graph()` DAG 可视化 | 5 个脚本的流程，看文件名就懂 |
| `prompt_restrict` 类型检查 | 4 个 prompt，人工对齐足够 |
| 用 pandas 做 Storage | 为了对齐 DataFlow 引入重依赖，不值 |
| 把 5 个脚本合并回 Pipeline 类 | 见第 4 章，分开才对 |
| 引入 DataFlow 本体 | 我们要的是它的**抽象思想**，不是它的依赖树 |

---

## 8. 版本记录

**v0.2（2026-10-01，本次）**
- 新增第 0 章：v0.1 五项计划的**落地状态对照**（这是本次最大的修正）
- 补 DataFlow 出处 arXiv:2512.16676（v0.1 只有机构名）
- 目录结构改为**现状 vs 目标 diff**，标 ✅/❌/🔄/➖
- 第 3 章补"方案写的 vs 实际写的"及差异原因（storage 参数被省掉是有意的）
- 第 4 章说明"三个 Pipeline 拆成五个脚本**是对的**"，并修正"4 模型"的过时表述
- 实施顺序**只列未完成的**，每条加**可执行验收标准**
- 第 6 章裁决三份文档的优先级冲突：重构降级为支线

**v0.1（初版）**
- 借鉴 DataFlow 提出 Operator/Storage/Serving/Prompt/Pipeline 五层抽象
- 提出三个 Pipeline 与 3.5 天实施计划
