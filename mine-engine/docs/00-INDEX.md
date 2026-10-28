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
| 05 | [科研 idea 清单](./05-ideas.md) | 要发论文的人 | 13 个 idea，含创新性/工作量/风险评分与优先级 |
| 06 | [工程改进与路线图](./06-roadmap.md) | 写代码的人 | M7–M10 排期 |
| **07** | [**合成环境数据：别人的经验与我们的差距**](./07-synthetic-environment.md) | 做引擎的人 | 对标 AWM(1,000 合成环境) + 中科院环境工程综述，列出我们缺的三件工程件 |
| **08** | [**评测这门手艺：陷阱、指标、补了什么**](./08-evaluation-craft.md) | 做评测的人 | 八个常见陷阱 + 评测报告必备清单 + 环境四维体检 |
| **09** | [**合成数据与环境工程：三坐标校准手册**](./09-synthetic-env-playbook.md) ⭐ | **先读这篇** | 用 **ALE / ALE-Bench / Harbor** 三个坐标重新梳理全盘：怎么造环境、怎么封装、怎么判分、怎么让分数不封顶 |
| **10** | [**行动方案（草稿 · 待审核）**](./10-action-plan.md) 📌 | **拍板的人** | 零基础可读，全程用一个真实例子讲到底；四步走 + 6 个待决策点 |
| **11** | [**这个领域的基础（从零讲起）**](./11-fundamentals.md) 🌱 | **零基础的人** | **先看这篇**。用"一场考试"讲清 Agent/环境/benchmark/harness，<br>收录 CSDN 与小红书的四种讲法，再讲 ALE / ALE-Bench / Harbor 三件事，<br>最后逐块对照"这些基础如何拼成 AuLE" |
| **12** | [**真实模型接入与踩坑记**](./12-真实模型接入与踩坑记.md) 🔌 | **要真跑的人** | 三组 key 实测结论、模型名静默换名、thinking 截断陷阱、真实 benchmark 数据、单价来源、<br>**第 7 节：难度旋钮实跑暴露的 4 个"看似生效实则失效"的坑** |
| **13** | [**难度旋钮验收报告**](./13-难度旋钮验收.md) 📈 | **要写论文的人** | 第四步的真实验收数据（3 样本×6 档×3 次）：难度刻度 → F1 / 误报率 / 耗时 / 成本曲线，<br>三条验收逐条判定 + **分样本拆解**（均值会掩盖方向相反的单题效应）、四个"看似生效实则失效"的坑、诚实的局限 |
| **14** | [**架构与基础原理（配真实代码例子）**](./14-架构与基础原理.md) 🧩 | **想搞懂"这套系统到底怎么搭的"** | 三层架构（出题/考试/难度）+ 四组件抽象；<br>**核心原理：把判断题改造成实验题**——不问"有没有漏洞"，而是"改坏后行为是否按预期变了"<br>（用 `sample-0001` 真实挪一行 + 自动写答案举例）；<br>差分验证三重闸门、判分严度≤标注粒度、难度旋钮实测曲线、跨赛道同构性证明 |
| **15** | [**术语审查与换词对照**](./15-术语审查与换词对照.md) 📖 | **要对外发言/写论文的人** | 逐词判定"埋雷/健康体/诱饵"是自造还是行业真词，<br>给出学界对应词与出处：埋雷=**vulnerability injection**、健康合约=**seed program**、<br>诱饵=**chaff bug**(CCS'18)、差分验证=**differential PoV oracle**、PoC 打穿=**PoV verification**；<br>并说明哪些自造词**故意保留**（考试院/旋钮）、哪些**代码不该改**（planted 会破坏 7 样本）|
| **20** | [**S1 实测报告：真实 judge 的真 FNR/FPR**](./20-S1实测报告.md) 🎯 | **拍板的人 / 合作方** | ✅ **go/no-go 闸门已通过：GO，叙事成立。**<br>真实 DeepSeek judge端到端漏判率 **FNR\*=0.500**（95%CI [0.423,0.577]，n=160，flash）<br>/ **0.380**（[0.291,0.478]，n=100，v4-pro），**两个 CI 都远高于0.20 阈值**。<br>设计：3 个 arm 是"我们帮它多少"的减负梯度（naive /预求和 workpaper / +程序清单 checklist），<br>取**最宽松 arm C + 端到端**是**对自己不利的一侧**，判据跑前写死不许事后改。<br>**三条比 FNR 更硬的发现**：①**漏判是"宣称做过却没做"**——<br>offbook 虚增 22万，`o_tie_detail` 已破坏，judge 仍答"勾稽、递推、恒等式均一致"；<br>换更强的 pro 端到端 FNR 反而 1.000 →解法不是换模型而是**强制执行**；<br>②**结论-理由自相矛盾**——arm B 上 **54.6%** 的报警被它自己的 reason 否定<br>（"累计折旧/原值=5%，折旧正常，无异常" 却填 `anomaly_found=true`），<br>推理对了结论写错了，**这类错误不进入任何准确率统计**，且廉价可修；<br>③**能力提升只买到检测、没买到归因**——pro 检测层 FNR 0.494→0.070，归因层 0.012→0.333，FPR 0.000→0.800。<br>**两次差点得到假 GO（都是我的题错，不是模型）**：thinking 烧光 token → 4/5 空答案 → 分母只剩 1 →报"NO-GO"；<br>题面缺"同年度 4 季度"与"权责发生制"口径 → FPR 假性1.000，补口径后归 0。<br>→ **测量模型能力前必须先证明题是无歧义的**｜ 代码：`vts/judge_probe.py` + `run_s1_judge_probe.py` + `run_s1_selfcheck.py`（62 项离线自检）｜<br>下一步：把实测 FNR/FPR 接进 `rl_impact.py`（现在那张图仍用假设参数）；测"读 reason 而非 flag"能救回多少 |
| **21** | [**科研进展方案（S1 之后 · 当前唯一有效路线）**](./21-科研进展方案.md) 🚀 | **拍板的人 / 要开工的人** | **本文取代 19 §7 的"下一步"表。**<br>**S1.1 新结果**：把 S1 实测误差接进 `rl_impact.py`，第一次有了真实落点——<br>**更强的 judge 会把 GRPO 训练方向带反**：pro 正确解优势 **−0.2025 → SIGN_FLIP**（精确率仅 0.437），<br>而更弱的 flash **+0.5671 → OK**。**"买更强的 judge ≠ 买更好的 RL"** 从说法变成可算结论。<br>**S2 新结果**：翻转判定对组大小 **G=4→32 基本不变**，只有退化率 25%→0% ⇒ **S2 降级为文档说明**。<br>⚠️ **诚实边界**：pro 的 FPR=0.800 只有 40 个干净样本，CI [0.652,0.895]；<br>取最不利联合边界（FNR 0.291 / FPR 0.652）时优势变 **+0.0628 → OK**，**结论尚未钉死**。<br>**解法已算好：干净样本 40→80~120（注入 100→300），成本约 $2** ⇒ 列为 P0。<br>**两个关键判断**：①**第二个域用合约域自己**（`forge test` 是天然强 oracle，成本降一个量级，且把两条线焊死）；<br>②**AuLE 统一叙事**——verifier 审计不是另一件事，正是"出题引擎"成立的前提。<br>｜ 代码：`run_s11_rl_impact_real.py` → `results_s11_rl_impact_real.json` ｜<br>配图：[**Fig8 科研流程图 v5（四步 + 闸门 + 实测落点）**](./figures/fig8-research-flow.svg) ·
🌟 [**Fig9 零基础定位图（不含任何缩写）**](./figures/fig9-beginner-orientation.svg) |
| **28** | [**A0 前置诊断与方案迭代 v5（当前最新方案）**](./28-A0前置诊断与方案迭代v5.md) 🆕 | **要开工的人 / 拍板的人** | **当前最新。** 实测：四个注入算子对应四条不同审计认定，但违反的 oracle 集合**完全相同**（均 `{o_tie_detail, o_rollforward}`），四条 oracle 里**两条从未被触发** ⇒ "四档难度"被**压成一档**；瓶颈由"造算子"变为"让 oracle 对认定敏感"。<br>**✅ F1–F4 已实施并通过验收**：oracle 4→**7 条**（按认定分层）、签名矩阵 **4/4 分离**、`run_f4_acceptance.py` **PASS**（干净账套 **0/600** 误报、7/7 oracle 全部用上、6/6 两两可分），零 LLM 成本约 3 小时。<br>**两个代码缺陷已修**：`o_policy` 曾是**死代码**（判定方向与注释相反、阈值 0.10 永远够不到实测最大 0.05）、`o_equation` 从不参与判别。<br>🔴 **§3.0.1 四版被实测否掉的设计是本轮最贵的经验，勿重犯**。<br>⚠️ **诚实边界**：`offbook` 仍未取得认定级信号。<br>**待你判断 3 件事**：①是否现在投 A0 的 **$8–12**（我判断可以投，但建议先 A1 补样本钉死 τ 符号 ~$2）；②是否补 F5（`o_cash_receipt`，倾向先不补）；③`equation_break` 算不算一档难度（维持不算）｜ 代码：`run_f4_acceptance.py` |
| **29** | [**学术规范与新手架构图导读**](./29-学术规范与新手读图.md) 🆕 | **写论文的人 / 零基础的人** | **写论文前的约束清单。** 名字消歧表（6 个名字、历史上**引错 4 次**）+ 引用纪律五条 + 🔴 **禁引清单**（宁可留白也不引假数字）+ 数字纪律（每个数字必须附：方法 / 次数 / CI / 谁批准）+ **J 必须分层报且写明符号归属** + **设计参数必须标注"未标定"**（如 `DEPR_MIN_RATIO`）+ 5 条不可越界红线。<br>**§7 是新手读图入口**：用"考试院"类比讲清**造题 / 判分 / 考务**三件事里"阅卷老师自己有没有看错"从来没人负责。<br>**配图**：🌟 [**Fig9 零基础定位图（全程零缩写）**](./figures/fig9-beginner-orientation.svg) → [**Fig8 科研流程图 v5**](./figures/fig8-research-flow.svg) |
| **27** | [**审计域细分与科研/工业界投向调研**](./27-审计域细分与科研工业界投向调研.md) | 要定域的人 | 「审计」的细分不是国家/企业，而是**三个法律主体 × 两个内容维度**：国家审计（审计署）= 政府审计、社会审计（会计师事务所）= 财务报表审计、内部审计 = 内控评价。<br>⚠️ **只有「社会审计中的财务报表审计」才是财务审计/会计**，其余两个不是。<br>科研界几乎全在**发现（detection）**方向（异常检测/舞弊预测/分录测试）⇒ **「判分器可靠性审计」在科研界仍是空白，判断成立**。<br>🔴 甲方侧新发现：审计署官方自陈的 LLM 风险清单里，**缺的那一环正是我们的产品** |
| **26** | [**学科术语规范与三领域正式定位**](./26-学科术语规范与三领域定位.md) | 要写论文的人 | 修正一个术语硬伤：项目里有**两个不同的"审计"被同一个词覆盖**。建立自造词→学科标准词替换表（补 [15](./15-术语审查与换词对照.md) 只做去军事比喻的部分）。<br>核出**三条一直白拿却从没引用的学科红利**（其中一条决定性）：FNR = 审计准则的**检查风险**（PCAOB AS 1101）；`J = 1−FPR−FNR` = **Youden's J**（1947）。<br>重写**审计（工程）/ 金融 / coding 长时程**三领域的规范表述 |
| **25** | [**全坐标对比与方向定稿（Table 1）**](./25-全坐标对比与方向定稿.md) 🔴 | **要定方向的人** | **方向不变，但主命题必须换掉一条腿。** 本轮新证据里 **2 篇直接吃掉"RL 后果"这条腿**（Noise-corrected GRPO 2510.18924、Delay/Plateau/Collapse 2605.02909 COLM'26），**1 篇吃掉"会计域没人测"**（FinVerBench 2605.29586）。<br>⇒ 剩下唯一未被占的位置：**可构造参照 oracle + 难度连续参数化 + 误报为何致命**。<br>**§1 就是论文 Table 1**（补 22 号文档判的 Critical 缺口）；最接近的一篇是 **Where the Verifier Fails**（2609.01354）｜ 另见 [24](./24-AutoBenchmark借鉴.md) |
| **24** | [**AutoBenchmark（Meta RAM）精读与借鉴清单**](./24-AutoBenchmark借鉴.md) | 要定方向的人 | research agent **端到端自动出题**并产 Harbor 兼容包（Jason Weston 组）。技术报告未发，所有数字来自官方博客正文并逐条核对。<br>⚠️ 先消歧：**AutoBenchmark ≠ Auto-Bench**（后者 arXiv:2502.15224 因果图发现，无关） |
| **23** | [**从零到一科研全链路审查（43 个 skill 逐环节过）**](./23-科研全链路审查.md) 🆕 | **拍板的人 / 要开工的人** | **判定：Accept with Revisions**（不是Reject）。<br>**技术侧站得住，论文侧还没站住** —— 4 个致命缺陷里**3 个是逻辑问题、只有 1 个是实验量问题**。<br>**用 `idea-evaluator` 的 10 条致命缺陷审计，命中 3 条**：<br>🔴 **F6 不可验证主张（CRITICAL）**——我们主张"能测出误差-难度**曲线**"，<br>但 S1 **只在一个难度档上测过**；曲线只在**合约域**用 deepseek-flash 做过，会计域+judge 任务没做。<br>⇒ 补3 档曲线是 1–2 天的实验量，故判 MAJOR 而非 CRITICAL；**两周内补不出就升级为 CRITICAL**。<br>🟡 **F9 为技术找问题**（起点是verifier 注入引擎，审计域后接）⇒ 需把 offbook 100% 漏判写进 Intro 开头当动机锚点。<br>🟡 **F8 范围过大**（贡献列了 6 项，skill 红线 4 项）⇒ 论文只留 3 项：审计方法+实测发现+GRPO 后果。<br>**五维打分**：Cheaper **9**（唯一有实测硬支撑：1100人时→0.35ms/题）、Stronger **7**（判据跑前写死+决策守卫+repeat=3）、<br>Higher **5**（我们不改进 verifier，只测量它——**这维天然低分且应该接受**）。<br>**范式探针 3/4 Yes**（Technology Cycle 只部分命中）⇒ **卖点在"被回避的方法论问题"，不在"LLM 便宜了"**。<br>**诚实加分项**：S1.1 已自报FPR 的 CI 宽、结论随边界翻转 —— 建议把"结论随边界翻转"本身写成一条 Finding。<br>**瓶颈不是算力是写法**：4 个 Critical 里 3 个零实验成本（人工盲审 0.64h、Table 1、贡献砍半），<br>要花钱的只有补模型~$3–5 + 曲线~$2。｜ **工具**：43 个 skill（`idea-evaluator` / `benchmark-paper-template` /<br>`academic-pipeline` / `pre-submission-reviewer` / `nature-statistics` / `nature-ref-verifier` …） |
| **22** | [**五支柱审计（用 benchmark-paper-template 框架审v4）**](./22-五支柱审计.md) 🔴 | **拍板的人 / 要投稿的人** | ⚠️ **审计判定 NOT READY：Critical 3 / Major 4 / Minor 3。**<br>**最重要的一条是逻辑漏洞，不是实验不足**：原gap 论证「测verifier 要 1100 专家小时」<br>**站不住** —— 行业建议明写「手工标 200–500 条就能测 FNR」，那是"加几条样本"，<br>属**成本缺口**而非**结构缺口**，而成本是资本能解决的。<br>**gap 已改写**（已落进 19 §3）：从「贵」改为「**只能得一个点、得不到误差-难度曲线**」，<br>辅以三条实测差异（难度可参数化 / 边际成本 0.35ms 恒定 / 单点vs 曲线）。<br>**五支柱判定**：Construction Pipeline ✅（范式同 nvBench 2.0，DIC 800/800）、<br>Evaluation Framework ✅ **最强**（两层 FNR 分层是原创贡献）、<br>Research Gap ⚠️已修正、Empirical Findings ❌ **Critical**（仅 2 模型 vs 要求 10–15，<br>无人工基线，未写 *Finding X* 句式）、Companion Method ➖ NA（可辩护）。<br>**QC 最大缺口**：**没有任何人工验证过账套"像真的"** —— S5 审计师盲审从nice-to-have 升为 **Critical**。<br>**Table 1 benchmark 对照表缺失** —— checklist 明写"缺comparison table 可以毁掉录用"。<br>**5 条 Finding 候选已拟好**（数据已在手，零实验成本）：<br>①换更强 judge 只买检测不买归因 ②54.6% 报警被自身理由否定 ③恒等式对 4 种舞弊全不可见<br>④误报 0 时漏判 100% 也不翻转 ⑤66–100% 组 σ=0 无报错停摆｜ **方法来源**：`benchmark-paper-template`（HKUSTDial） |
| **19** | [**课题重定位 v4（当前唯一有效方向）**](./19-课题重定位-v4.md) 🎯 | **拍板的人 / 合作方** | ⚠️ **v3 的核心主张已被检索证伪并作废。**<br>C 类不是空白——**WebGrader**(2608.06474, NL→可执行 Flow Contracts→RL reward)、**AutoPyVerifier**(2604.22937, +55 F1)、**Pajama**(2607.22561, 程序化判分 47× 快)、**SpyRL**(COLM'26) 都已覆盖。<br>**教训**：自造术语=检索盲区=把"我没搜到"误当"没人做过"。<br>**新主张**：不去攻"造 verifier"（已成熟），去攻 **verifier 审计**——<br>它人人都在用但没人测过，因为**测它需要一个昂贵的参照 oracle（FAB 烧 1100 人时）**。<br>⚠️ **该 gap 论证已被 [22](./22-五支柱审计.md) 修正**：原"贵"站不住（行业建议手工标 200–500 条即可），<br>已改写为"**只能得一个点、得不到误差-难度曲线**"，见 19 §3 新增段。<br>**已实测 4 条结论，3 条反直觉**：①**结构性不可见**——`o_equation` 不在任何手法的破坏集里，只查恒等式的 verifier 恒定漏判 100%，调容差救不回来；②漏判必须拆**检测层/归因层**（`tie_only` 检测 0% 但归因 80%）；③**误报率=0 时漏判升到 100% 也不翻转训练方向**（推翻社区直觉），翻转阈值=FPR 0.2→FNR 0.8、0.5→0.5；④**第三种失效：无梯度退化**（FNR→1 且 FPR=0 时 66–100% 组 σ=0，停摆但不报错）。<br>解析式 vs MC 最大偏差 0.27，**审计 verifier 不需要跑 RL**。<br>✅ **S1 已完成，见 [20](./20-S1实测报告.md)**（真实 judge FNR\*=0.50 → GO）｜ 代码：`vts/verifier_audit.py` + `vts/rl_impact.py` + `run_vts_regression.py` ｜<br>**配图（v4 专用）**：🌟 [**Fig0 科研方案总图（缺口→方法→证据→交付→路线→边界）**](./figures/fig7-aule-research-plan.svg) · [Fig1 科研架构三层结构](./figures/fig4-verifier-audit-architecture.svg) · [Fig2 错误预算矩阵与结构性不可见](./figures/fig5-error-budget-matrix.svg) · [Fig3 DataFlow 六层栈落点](./figures/fig6-dataflow-stack-positioning.svg) |
| **18** | [**科研方案 v3（方向已被 19 证伪，保留方法与实测）**](./18-科研方案v3与代码实现方案.md) | 参考 | ⚠️ **其"扩展 RLVR 到无 oracle 领域"的主张已被 19 证伪**，<br>但**方法层仍全部有效**：C 类三条性质、**差分隔离证书 DIC**、4 条会计约束、4 个舞弊算子、`vts/audit_core.py`。<br>已实测：种子账套 3200/3200、DIC 800/800=100%、0.64ms/样本、E6 复用性每题 0.35ms 恒定。<br>两条反直觉会计发现：①「每手法恰好破一条 oracle」不成立；②**费用资本化/折旧不足并不破坏会计恒等式**，可检测性来自表账不符 ｜ 代码：`vts/audit_core.py` + `run_e6_reuse.py` |
| **17** | [**课题重构方案 v2**](./17-课题重构方案-v2.md) | 拍板的人 / 合作方 | ⚠️ 主张与实验以 [18](./18-科研方案v3与代码实现方案.md) 为准，本篇的**生态定位 §1–§3 仍有效**。<br>基于张文涛老师主页的三条新事实：生态是 **L0–L5 六层栈**、DataFlow 投的是 **SIGMOD 不是 NeurIPS**、<br>**LoopAI 已接 verl 但 Judger 是 LLM 造题自判**。<br>主战场定为电子数据审计（代码域本来就有 verifier，构不成 novelty）｜<br>配图 [fig2 六层栈定位](./figures/fig2-positioning-in-dataflow-stack.svg) · [fig3 审计域方法](./figures/fig3-audit-vts-method.svg) |<br>质量信号只有 LLM-judge 与分布启发式两类，都不是 ground truth；我们提供第三类——<br>**构造性标签**。含 H1–H4 假设、novelty 的诚实边界（明确写了什么不新）、<br>六个接入点 A–F 与 P0/P1/P2 节奏、五个实验设计、风险表、三件待向 lab 确认的事 ｜<br>配图 [fig1 科研架构图](./figures/fig1-research-architecture.svg) |
| — | [可视化报告 report.html](./report.html) | 所有人 | 一页看懂：痛点 / 脉络 / 定位 / 赛道 / idea / 路线图（⚠️ 内容停留在 v1 方向，与 [19](./19-课题重定位-v4.md) 不一致） |

> 🌱 **完全没基础？从 [11](./11-fundamentals.md) 开始**。
> 它不假设你知道任何名词，用考试比喻讲到底，并标明国内（CSDN / 小红书）怎么讲这套基础。
>
> 🧩 **想搞懂我们自己这套代码怎么搭的？读 [14](./14-架构与基础原理.md)**。
> [11](./11-fundamentals.md) 讲的是"行业怎么出题"，[14](./14-架构与基础原理.md) 讲的是"我们怎么搭、为什么这么搭"。

> ⚠️ **三个名字别搞混**（详见 [09](./09-synthetic-env-playbook.md) 第 0 节）：
> **ALE** = Agents' Last Exam（Berkeley RDI，arXiv:2606.05405）——判分纪律与防污染；
> **ALE-Bench** = ALgorithm Engineering Benchmark（Sakana × AtCoder，arXiv:2506.09050）——连续分与开放式上限；
> **Harbor** = 评测框架（laude-institute）——任务三元组与验证流程。三者不是同类。

### 已有沉淀（偏"内部设计决策"）

| 文档 | 内容 |
| --- | --- |
| [AuLE-设计文档.md](./AuLE-设计文档.md) | v0.3：三级考试体系、四维评分、已有实验结果（含 Level 2 打穿率） |
| [ALE-Harbor借鉴方案.md](./ALE-Harbor借鉴方案.md) | v0.4：ALE 三层难度/五阶段生产/Gate-and-score + Harbor 七阶段验证的逐条借鉴 |
| [AuLE-代码实现方案.md](./AuLE-代码实现方案.md) | **v0.2**：借鉴 DataFlow（arXiv:2512.16676）的重构设计。<br>已加**落地状态对照**——统一算子抽象✅已完成，storage/serving/prompt❌未做；<br>并裁决了与 [10](./10-action-plan.md) 的冲突（重构降级为支线） |
| [AuLE-前沿调研报告.md](./AuLE-前沿调研报告.md) | 前沿调研 |
| [vuln-injection开发清单-智能合约审计.md](./vuln-injection开发清单-智能合约审计.md) | M0–M7 可执行开发清单与 DoD |

**两套文档的关系**：已有沉淀回答"我们怎么建"；本次新增回答"我们怎么讲、怎么发论文、怎么扩赛道"。

### 🖼 配图索引（按"读图顺序"排，不是按编号排）

> 🌱 **零基础？直接打开 [新手读图指南.html](./新手读图指南.html)**：
> 一页网页，把下面三张图逐段拆开讲，附术语小词典与"最容易搞错的几件事"，不假设你知道任何名词。

| 顺序 | 图 | 给谁看 | 状态 |
|---|---|---|---|
| **0** | 🌟 [**Fig9 零基础定位图**](./figures/fig9-beginner-orientation.svg) | **完全没基础的人** | ✅ 最新（全程零缩写，一张图看懂"三件事里没人管的那一件"） |
| **1** | [**Fig8 科研流程图 v5**](./figures/fig8-research-flow.svg) | 要知道"我们做到哪一步" | ✅ 最新（四步 + 闸门 + 实测落点，同步 v5 方案） |
| **2** | [**Fig10 路线图**](./figures/fig10-roadmap.svg) | 要决定"接下来干什么" | ✅ 最新（P0 → A0 → verl → 合约域 → 盲审 → 交付） |
| 2 | [Fig7 ALE 科研方案总图](./figures/fig7-aule-research-plan.svg) | v4 时期的总图 | ⚠️ v4 口径 |
| 3 | [Fig4 verifier 审计架构](./figures/fig4-verifier-audit-architecture.svg) · [Fig5 错误预算矩阵](./figures/fig5-error-budget-matrix.svg) · [Fig6 六层栈落点](./figures/fig6-dataflow-stack-positioning.svg) | 读方法细节 | ⚠️ v4 口径 |
| — | [Fig1–Fig3](./figures/fig1-research-architecture.svg) | v2 时期 | ⚠️ 早期 |

> ⚠️ **编号有历史包袱**：`fig7` 在 [19](./19-课题重定位-v4.md) 里被称作 "Fig0"，
> `fig8` 在 [21](./21-科研进展方案.md) 里曾被称作 "Fig4"。**以文件名 `figN-*` 为准，不以文档里的叫法为准。**
> 源文件 `.mmd` 与 PNG 与 SVG 同名同目录（如 `fig8-research-flow.mmd/.png/.svg`）。
>
> 📐 **作图约束（beautiful-mermaid 把字号硬编码为 15px，改不了）**：
> 字看不看得清，只取决于**画布有多宽**——画布越宽，缩到页面宽度后字越小。
> 因此每张图的 SVG 宽度必须控制在 **≤1200**（当前 fig9=859、fig8=1160、fig10=633）。
> 超了就<b>拆图</b>，不要往一张图里塞更多节点。
> ⚠️ **还有一个坑**：节点**必须先定义、后连边**；把 `X{...}` 写在 `A --> X` 之后，
> beautiful-mermaid 会静默丢掉该节点（fig8 的闸门节点就因此消失过一次，且没有任何报错）。

---

## 三分钟速读版

1. **行业痛点**：所有公开 benchmark 一发布就开始腐烂——题目泄漏进训练数据，分数虚高。
 - EVMbench 用 cutoff 后真实事故做无污染重测，Agent 表现断崖下跌
 - **ALE 自己都只公开 10% 的题目（150/1490）来防污染**
2. **我们的解法**：不让题"被背下来"，而是**每次考试现出题**——
 程序化注入漏洞 + 差分验证证明"雷真是这次埋的" + 固定 seed 可复现。
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
| Level 1 · Detect | 🟡 早期 qwen 三轮跑测 F1=1.000（4 道独立题，已饱和、含金量低）；<br>**真实 DeepSeek 跑测（[doc 12](./12-真实模型接入与踩坑记.md)，v2）flash=0.730 / v4-pro=0.871** → 换难设置仍有区分度空间。<br>⚠️ 早期 1.000 已被真实跑测刷新，**对外以 doc 12 为准** |
| Level 2 · Exploit | ✅ 打穿率 50–83%；**tx_origin 是终极区分题** |
| Level 3 · 端到端 | 🔨 多文件仓库 + 四维打分，刚起步 |
| 数据集 | 7 个**样本目录** = **4 道独立题**（reentrancy / access_control / tx_origin / chaff bug）<br>+ 3 个 LLM 改写变体（`-v1`）→ 目标 50+（MVP DoD） |
| Harbor 导出 | ✅ 本次新增（`run_harbor_export.py`） |
| 跨赛道 | 🔨 三条赛道契约已定义，实现待做 |
| **环境四维体检** | ✅ 本次新增（`run_env_quality.py`） |
| **时间/成本双轴 + 饱和检测** | ✅ 本次新增（`engine/analytics/openended.py`） |
| 难度连续旋钮 | ✅ 已实现**并跑过真实验收**（`engine/operators/difficulty.py` + `run_difficulty_sweep.py`）；<br>两个模型 × 3 样本 × 6 档 = **108 次真实调用**（$1.51）：<br>· 误报率 0.00→**0.67**、耗时 **×17**、端点 F1 0.775→0.649<br>· **两条曲线在刻度 2 交叉**——flash 与 v4-pro 的难度排序反过来<br>（[doc 13](./13-难度旋钮验收.md)）<br>⚠️ 三个已知边界：**对已饱和的题无效**（甚至反向）；4 个旋钮里 `variation_k` 未接线；只测了同厂两个模型 |
| **旋钮静态体检** | ✅ `run_difficulty_lint.py`：括号配平 / 依赖符号已声明 / 无重名函数 / 无自曝身份；<br>18 项全过，**当场抓出 2 个会让整批样本编译失败的 bug** |
| **时间与成本记账** | ✅ 已落地（`run_benchmark.py` + `engine/llm/pricing.py`）；<br>口径为 **cost per solved task**；单价需自行配置，未配置显示 n/a |
| **防伪检查（dummy / oracle check）** | ✅ 已落地（`run_dummy_check.py`）；7 样本在 v1/v2 下全通过；<br>并揪出 v2 判分器的chaff 题 bug（已修） |
| **自我修正循环（题坏了喂回修）** | 🔨 骨架已实现（`batch_generate.py` 重试循环 + `VariationOperator.fix_variant`）；<br>把 forge 报错喂回 LLM 重生成，记录 retry_count；forge 实跑留 CI |
| **真实端到端跑通** | ✅ 已接真实 DeepSeek key 跑通 7 样本（v2，repeat=1）：<br>flash F1=0.730 / $0.0037 / 5-7s；pro F1=0.871 / $0.0456 / 6-7s。<br>⚠️ repeat=1 不显著；详见 [12](./12-真实模型接入与踩坑记.md) |
| 离线自测 | ✅ 已落地（`run_offline_smoke.py`，**19 项**断言）、`run_implementation_smoke.py`（旋钮+自我修正），均无需 API key |

### 我们在学术分类里的位置（写论文必用）

中科院自动化所综述 arXiv:2606.12191 把环境自动合成分为两大流派六条路径，
我们属于**符号合成 → 从零合成**（from-scratch symbolic synthesis）——
不依赖任何真实数据输入，靠程序化注入漏洞凭空造题，是扩展性最强但难度最高的一档。

综述对这一档的判语是"难点在于保证自动生成内容的**逻辑自洽性和执行正确性**"——
而这恰好被我们的**差分验证**（`forge test` 前后对比）解决了。这是我们最硬的学术立足点。

同类旁证：**gg-bench** 用随机采样发明全新游戏规则来避免训练污染，
与我们"现出题抗污染"是同一思路。

### 环境四维体检结果（2026-10-01 实测，`python run_env_quality.py`）

| 维度 | 得分 | 判定 |
| --- | --- | --- |
| 正确性 | n/a | 未测——需跑黄金解答自测补 blocked rate |
| 多样性 | **0.3665** | **narrow**：类别均衡度 0.975 很高，但结构离散度仅 0.173——**雷型分散但代码结构高度同质** |
| 复杂性 | **0.3673** | 5 档难度只占了 2 档，梯度没铺开 |
| 忠实度 | n/a | 未测——**最大盲区**，缺真实任务锚定集 |
| **综合** | **weak (2 dims unmeasured)** | 四维里我们只稳住了"正确性"这一维，而它是四条中最成熟的 |

**这张表是本轮最重要的发现**：我们做出了四条里最容易的一条（正确性），
难的三维（多样性/复杂性/忠实度）基本没碰。详见 [07](./07-synthetic-environment.md)。

### Level 2 实测（关键数据，勿丢）

| 模型 | 打穿率 | 关键失败 |
| --- | --- | --- |
| qwen3.8-flash | 5/6 | tx_origin 变体 fail "not owner" |
| qwen3.8-max | 5/6 | tx_origin 原题 fail "not owner" |
| deepseek-flash（网关把 v4-flash 静默改名，见 [doc 12](./12-真实模型接入与踩坑记.md)） | 4/6 | reentrancy 变体 no_code；tx_origin 变体 fail |
| deepseek-v4-pro | 3/6 | reentrancy 截断；access_control 变体 no_code |

**三条发现（写论文要用）**：
1. **Detect 满分 ≠ Exploit 打穿**——同一个模型在两种模式下排名会变
2. **tx_origin 是终极区分题**——模型不知道 Foundry 要用 `vm.prank(sender, origin)` 双参模拟
3. **deepseek-v4-pro 打穿率（3/6）反而低于 flash（4/6）**——这不是推理能力问题，
 是长代码生成时 `max_tokens=4096` 不够导致**截断**（sample-0001 直接 `vm.deal(vict` 断掉）。
 ⚠️ 这是一个**评测假象**，若不修正会把"生成长度限制"误当成"能力差异"。
 已在 `engine/llm/client.py` 修复：默认上限提到 4096、`.env` 给到 8192，
 并加了 `truncated` 检测——空答案会被显式报警（`--strict` 直接报错），不再静默记 0 分。
 （同样会坑 Detect：v4-pro 在 `max_tokens=1024` 时曾返回空 findings，HTTP 200。）

---

## 项目内 prompt 资产清单（已全部审阅）

| 位置 | 资产 | 作用 |
| --- | --- | --- |
| `engine/agents/audit_agent.py::PROMPT_STRATEGIES` | `standard` / `conservative` / `aggressive` 三套 | 同一模型换审计策略做 A/B，测"宁缺毋滥 vs 宁多勿漏" |
| `engine/agents/level3_agent.py::_PROMPT` | 多文件仓库端到端审计 | 含"区分真漏洞和chaff bug"指令 |
| `engine/agents/exploit_agent.py` | 让模型写 Foundry 攻击 PoC | 从"会说"升级到"能打穿" |
| `engine/operators/variation.py::VARIATION_SYSTEM` | 语义保持改写 | 一道题长出多个变体，解决"确定性算子=复制粘贴" |
| `engine/scorers/report_score.py::_TYPE_ALIASES` | 漏洞类型别名归一化表 | 判卷时的中英文别名词典（本次已修否定词误判 bug） |
