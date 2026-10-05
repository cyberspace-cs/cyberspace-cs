# 24 · AutoBenchmark（Meta RAM）精读与借鉴清单

> 版本：2026-10-05 ｜ 状态：**高优先级，已影响论文定位**
> 来源：`https://facebookresearch.github.io/RAM/blogs/autobench`（Jason Weston 组，Meta RAM）
> 完整技术报告**尚未发布**，本文所有数字均来自官方博客正文，已逐条核对。

---

## 0. 先消歧：有两个"AutoBench"，别引错

| 名字 | 是什么 | 出处 | 和我们的关系 |
|---|---|---|---|
| **AutoBenchmark** | research agent 端到端**自动创建** benchmark 并自我迭代 | Meta RAM 博客，Jason Weston 组 | **本篇。必须引，且必须改写法** |
| **Auto-Bench** | 因果图发现，测"AI 能否做科学发现" | arXiv:2502.15224，NUS + Meta | 无关，不要引 |

小红书那张图配的是**第一个**。图里三个关键词对得上：Harbor 格式、三步pipeline、human-in-the-loop。

---

## 1. 它做了什么（一句话）

> **让 research agent 端到端出题，产出一个 Harbor 兼容评测包；
> 闭环是"出题 → 让 solver 做题拿难度信号 → 用 LLM judge 审题质量 → 改题"，
> 并用不参与闭环的 held-out solver 独立测难度是否迁移。**

### 1.1 三阶段

| 阶段 | 内容 | 关键设计 |
|---|---|---|
| **S1 Proposal** | 决定测什么（construct）→ 怎么测（operationalization）→ 找并**保存**一手来源 → 实例化成可跑任务 | agent 承担了人类出题人的全部决策：solver 看到什么、evidence 给什么、ideal answer 含什么、部分分怎么给、reference solution |
| **S2 Solving** | 1~2 个 solver agent 在 agent 指定的容器里做题，answer judge 按agent 写的 criteria 判分 | 这个分数是闭环的**难度信号**，分数越低题越难 |
| **S3 Review** | **LLM judge 审 research agent，不是审 solver**。五项criteria：construct validity / correctness / feasibility / usefulness / overall verdict | 任一项不过 ⇒ 该 iteration 被拒 ⇒ 不能当下一轮 parent |

### 1.2 三个我们必须记住的工程细节

**① parent 不一定是上一轮——是历史最低分的 accepted iteration。**
低分优先，但被 judge 拒过的、有缺陷的、或者分数比历史最好的更高的，都不能当 parent。

> 官方给的实例：Rebuttal Bench iteration 5 拿了当时最低分 47.4，
> 但**没通过 feasibility**，于是循环回退到 iteration 3 继续，最后 iteration 8 拿到 43.5 且五项全过。
> **"分数最低"和"分数最低且合格"是两件事。**

**② reference solution 是一道硬闸门。**
任何 solver 跑之前，先用agent 自己写的 reference solution 跑一遍**真实 verifier**，
**得分 < 0.9 直接拒收**，退回让 agent 修，每轮至多 10 次提交机会。

> 这是一条极便宜的质量闸门：oracle 自己过不了自己的 scorer，这题就是坏的。

**③ external solver 是独立审计器，不进反馈。**
不参与闭环、结果**不写回** research agent 的 memory。
便宜的（Nemotron-30B）每轮跑，出独立难度轨迹；贵的（Claude Opus 5）只在选定的 best checkpoint 上跑。

### 1.3 四个 human-feedback 设置（这是论文真正的实验轴）

| 设置 | 人给什么 | 锁定了什么 |
|---|---|---|
| (i) 无反馈 | 无| 全自主，连领域和 construct 都自己选 |
| (ii) 粗粒度 proposal | **一句话**说想测什么 | 锁"测什么"，"怎么测"全给 agent |
| (iii) 细粒度 proposal | 详细 task spec + **人工 curate 的一手来源清单** | 锁"测什么"+"很大一部分怎么测" |
| (iv) 细粒度 proposal + execution | (iii) 基础上每轮给下一步建议 | 再加"循环执行中有人带" |

### 1.4 数字（必须准确引用）

| 设置 | Muse-Spark 1.1 (in-loop) | Muse-Glimmer-30B (in-loop) | Nemotron-30B (held-out) | Claude Opus 5 (仅 best ckpt) |
|---|---:|---:|---:|---:|
| 全自主、无反馈 | 90 | 84 | 80 | 98.0 |
| Rebuttal + 粗粒度 | 84.4 | 83.7 | 81 | 83.1 |
| Rebuttal + 细粒度 | **43.5** | 51.2 | 39.1 | 65.9 |
| Graveyard + 粗粒度 | — | — | 75.4 | 90.7 |
| Graveyard + 细粒度 | — | — | **52** | 84.4 |

三条主结论：

1. **细粒度 proposal 反馈在 6 个(benchmark, solver) 组合上全部把分数压低 28–46.5 分。**
2. **粗粒度反馈基本没用。** Rebuttal 上只降 0.3，Nemotron 上反而涨 1分。
3. **execution 反馈能救活停摆的循环。** Figure 3 在 iteration 6分叉，两支 agent/construct/来源完全相同，
   一支给人类指导：`64.2 / 54.2 / 48.8`；另一支不给：`88.1 / 85.6 / 83.8`。
   **差值在 held-out solver 上最大（35.0）**，说明难度提升不是过拟合。
   三条人类指导全部关于 instantiation（跑多长的 job、用完整文件而非片段、按行为测试打分），**没有一条关于"测什么"**。

### 1.5 LLM judge 抓出的三类缺陷（低分看不出来）

1. **答案泄漏** —— answer key 写进了 solver 能读的 task assets。从分数看和"题太简单"一模一样。
2. **construct 太浅或已被记忆** —— benchmark 区分不开 solver。
3. **引用的来源根本没被 retrieval/保存** —— creator 声称用了某来源，实际没有。**可以和数据上的任何分数同时出现，所以单看分数永远发现不了。**

全自主那轮：前 3 轮分数都是 100.0，iteration 1 挂 5 条criteria、iteration 3 挂 2 条、iteration 4 才首次全过。
官方原话：**"只按分数挑，会选中那些被 verifier 拒掉的 iteration。"**

### 1.6 它明确不做的事（= 我们的空间）

- **不假设存在强 solver 为正确性背书**（原文明确说这点与 Autodata 不同）。⇒ 它没有独立参照 oracle。
- 难度**不可调** —— 没有旋钮，10 instances × 10 iterations 是固定合同。
- **完全没测 judge/judge 的误差率**，也没测误差对下游 RL 的后果。
- 五条 quality criteria 的 rubric、judge 间一致性、人类校准 —— **一项都没报**。
- **一个成本数字都没有**（无 token / 无美元 / 无 GPU 时）。
- 无置信区间、无显著性检验、无重复 run（无反馈那条只有**一次**自主 run，两个 row 共用）。

---

## 2. 和我们正面对照

### 2.1 重叠区（危险，必须承认）

| 我们的东西 | AutoBenchmark | 判断 |
|---|---|---|
| "会自己出题的考试院"（线 A / `mine-engine`） | **正是它的主命题**，而且做得更完整（Harbor 包 +闭环 + held-out 审计） | 🔴 **叙事被抢。自动出题不能再当卖点** |
| 产出 Harbor 兼容包 | 它的标准输出格式 | 🔴 **不能当差异点**，`run_harbor_export.py` 是准入门槛不是贡献 |
| 用外部独立信号审计"优化是否过拟合" | held-out solver 每轮测难度迁移 | 🟡 思想撞车，但**度量对象不同**（见2.2） |
| 独立的、agent 之外的判据 | LLM benchmark-quality judge（五项 criteria） | 🟡 **这是它最大的软肋，正好是我们的靶子** |

### 2.2 空白区（我们的位置因此更清晰了）

> **它审的是"题出得好不好"（质量审查，五条主观 criteria）；
> 我们审的是"裁判判得对不对"（误差率，(FNR, FPR)，可量化、可预测后果）。**

更精确地说：

| 维度 | AutoBenchmark 的 verifier | 我们的 verifier 审计 |
|---|---|---|
| 被审对象 | benchmark（题目 + 环境 + criteria） | scorer / verifier / LLM judge（判分器本身） |
| 判定方式 | LLM judge 打五项主观 criteria | 参照 oracle **精确**给出 (FNR, FPR) |
| 参照从哪来 | 没有参照，只有 judge 的意见 | **构造出来的 oracle**，零人工标注 |
| 误差是否被量化 | ❌ 完全没测 | ✅ 7 个 verifier 全部精确测出 |
| 误差的后果 | ❌ 没测 | ✅ 接进 GRPO 解析式pro 优势 **−0.2025 → SIGN_FLIP** |
| 失效形态分类 | ❌ | ✅ 翻转 / 无梯度停摆 / 精确率崩塌 三种分开 |

**⇒ 一句话话术：**
> *AutoBenchmark 建立了"agent 能自己出题"这件事，但它的题的质量由一个**未被审计的 LLM judge** 说了算。
> 我们不评价题的质量，我们**测量判分器本身的误差**，并证明这个误差会把RL 训练方向带反。*

### 2.3 最强的一击：他们的 S3 就是一个待测 verifier

他们把 `Muse-Spark-1.1` 同时用作：proposer、in-loop solver、answer judge、**benchmark-quality judge**。
**四个角色同一个模型，且这个 judge 决定整轮iteration 生死——却零误差刻画。**

而他们自己列出的三类缺陷，恰好就是我们 FNR/FPR 要测的东西：

| 他们的缺陷 | 对应我们的哪个量 |
|---|---|
| 答案泄漏到 assets ⇒ solver 接近 ceiling | 难度信号被污染（他们没测，我们可测） |
| construct 太浅/已被记忆 | **这类 verifier 对已饱和题无效** ←正是我们 `13-难度旋钮验收` 的结论 |
| 引用来源未真正保存 | **oracle 未真正接入 ⇒ 声称的判据不生效** ← 与我们的"结构性不可见"同源 |

> 他们已经发现了现象，**但没有工具去量化它，也没有把它接到下游训练后果上**。
> 这就是我们的位置：**给他们三缺的那一格。**

---

## 3. 五条可以直接抄的机制（附我们的落地位置）

| # | 他们的机制 | 为什么值钱 | 我们的落地 |
|---|---|---|---|
| **M1** | **reference solution 过真实 verifier，< 0.9 拒收**，每轮 ≤10 次修复机会 | 用极低成本挡掉"坏题"。我们目前只验了 oracle 自己（DIC 400/400），**没验 scorer 能不能被 oracle 判对** | `vts/` 加`solver_admission_gate()`：造完题先让 reference solution 走一遍被审 verifier，低于阈值拒收 |
| **M2** | **parent = 历史最低分的 accepted iteration**（不是上一轮） | 把"分数最低"和"合格"解耦，避免选中低分但有缺陷的题 | `mine-engine` 修订循环改父节点选择规则；也解释了为什么我们该保留 rejected 分支 |
| **M3** | **held-out solver 结果不进 feedback**，只作独立难度轨迹 | 防"对着被优化的 solver 变难"的reward hacking | 我们已有等价物（参照 oracle 不进 solver 反馈），**但要引它**并说明我们的 oracle 比 held-out solver **更强**：held-out solver 只能测迁移，oracle 能测绝对误差 |
| **M4** | **固定执行合同**（4 CPU / 16 GiB / 24h agent budget），全程不变 | 不变合同才能跨 iteration 比分数 | ✅ **已核查：对我们不构成约束。** 我们把耗时（1.8s→30.6s，×17严格单调）当难度硬指标，是因为 `run_difficulty_sweep.py` **没有设 timeout**，耗时是自然跑出来的真实工作量而非预算截断值。**但必须在论文里写明这一点** —— 否则审稿人会怀疑高刻度档位是被预算截断的假单调 |
| **M5** | **grounding material 开 session 前 hash + 只读快照** | 防"声称用了来源但其实没有" | 种子账套做同样的固化+ hash 落盘，直接堵住我们自己的"结构性不可见"被质疑 |

**另有一条纯组织范式值得抄**：
feedback 以**文件系统记忆**暴露（frozen snapshots / trajectories / answers / rubric judgments / verdicts 全部落盘，prompt 里只给路径），
每轮从 best checkpoint 播种 ⇒ 累积历史随轮次增长。
我们的 S1 测量台已经落盘 JSONL，但**没有"从最佳 checkpoint 播种"的回溯机制** —— 这是出题侧闭环的关键工程量。

---

## 4. 必须写进 related work 的三条威胁 + 应对

| 威胁 | 严重度 | 应对话术 |
|---|---|---|
| "AI 自己出题"不再是新命题 | 🔴 高 | 主命题改成 verifier 审计，出题降为**载体**。线 A 不再单独当卖点，只当"我们有第二个域 + 自带 forge oracle" |
| "用外部独立信号审计优化"已被占 | 🟡 中 | 差异在**度量对象**：held-out solver 测「难度是否迁移」（相对量），参照 oracle 测「判分器错多少」（绝对量，且能预测 RL 后果）。它测不了 `FNR`，因为它没有 ground truth |
| 他们若补上 verifier 校准，gap缩小 | 🟡 中 | **抢时间**。他们已列 future work 但优先级在"训练 proposer"和"元优化 harness"，**不在 verifier 误差 → RL 后果**。这是我们 P0/P3 的窗口期 |

**一条可直接用的交叉验证**（写related work 时很有分量）：
他们发现**粗粒度干预无效、细粒度干预才有效**（一句话反馈降 0.3 分甚至反升；详细 spec + curate 来源降 28–46.5 分）。
我们独立发现**旋钮对"已很难/已饱和"的题无效甚至反向**（0002 从 0.385 → 0.565）。
两个团队、两个域、同一形态的规律：**粗粒度调整无效，必须细粒度/结构化干预才有效。**
这条互相加固，且它是对方的一手证据，比我们自己说更有说服力。

---

## 5. 改动清单（按优先级）

| # | 动作 | 依据 | 成本 |
|---|---|---|---|
| **A1** | **论文标题与 intro 明确让出"自动出题"**，改打"审计判分器" | §2.1 叙事被抢 | 0，改文档 |
| **A2** | related work 加AutoBenchmark，并接上 §4 的交叉验证 | §4 | 0 |
| **A3** | 实现 `solver_admission_gate()`：reference solution 过真实 verifier，< 0.9 拒收 | M1 | 半天，无 LLM |
| **A4** | 种子账套 hash 固化 + 只读快照 | M5 | 半天 |
| **A5** | 论文里显式声明耗时未被timeout 截断（附 `run_difficulty_sweep.py` 无 timeout 的证据） | M4（防我们自己的口径漏洞） | 写作时补 |
| **A6** | 补一节"把我们的审计套在 AutoBenchmark 式 S3 judge 上会怎样"（讨论段，不做实验） | §2.3 | 1 小时写作 |
| **B1** | 预算/置信区间/成本必须报 | 他们**一项都没有** → 这是我们的免费差异化 | 随实验 |

---

## 6. 一句话结论

> **这篇不是威胁，是校准。它证明"让 AI 自己出题"这条路已经被走完了，
> 所以我们不能再把出题当卖点——但它用来判断题好坏的裁判，本身完全没有被测过，
> 而它手里正好握着整套"出题闭环"。我们要做的从来不是更好的出题机，
> 是给任何出题机装一个能证明"我出的题判分靠不靠谱"的仪表。**