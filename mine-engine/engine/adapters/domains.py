"""三条审计赛道的 adapter 契约。

设计原则（见 docs/04-three-tracks.md）：
  **一个赛道能不能做，只看一件事——有没有能自动跑的验证器。**
  有验证器，就能差分证明"雷是我埋的"，就能自动出 ground truth。

本文件是**契约 + 算子清单**，不是实现。要接入一个新赛道，
只需为该赛道实现四组件并把类名登记进来，编排层（Pipeline）一行不改。

四组件接口（engine/core/pipeline.py）：
    ArtifactGenerator.run(records) -> records   # 产出 clean_source / clean_artifact
    IssueOperator.run(records)     -> records   # 产出 planted_source + issues(ground truth)
    IssueValidator.run(records)    -> records   # 打 valid / validation_log
    ReportScorer.run(records)      -> records   # 打 scores
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class OperatorSpecLite:
    """赛道内的一个埋雷算子（设计阶段的登记项）。"""

    op_id: str
    name_cn: str
    method: str          # 埋法：健康体 -> 埋雷体 的具体变换
    signal: str          # 差分信号：验证器靠什么发现它


@dataclass
class AuditDomainSpec:
    """一条审计赛道的完整定义。"""

    key: str
    name_cn: str
    name_en: str
    hardness: str            # L1..L4，验证器硬度阶梯（见 docs/05-ideas.md I2）
    artifact: str            # 健康体是什么
    operators: List[OperatorSpecLite] = field(default_factory=list)
    validator: str = ""      # 验证器怎么证明（闸门描述）
    data_sources: List[str] = field(default_factory=list)
    compliance: str = ""     # 合规红线
    mvp: str = ""
    status: str = "planned"  # planned / wip / done


# ---------------------------------------------------------------------------
# 赛道一：国家审计（政府审计）
# ---------------------------------------------------------------------------

GOV_AUDIT = AuditDomainSpec(
    key="gov-audit",
    name_cn="国家审计",
    name_en="Government Audit",
    hardness="L3",
    artifact="合规的部门预算执行账套：预算指标 / 拨付流水 / 支出凭证 / 合同 / 验收单 / 决算表",
    operators=[
        OperatorSpecLite("fake_expense", "虚假列支",
                         "插入一张无对应合同与验收单的发票报销",
                         "凭证链缺环 + 违反《财政违法行为处罚处分条例》"),
        OperatorSpecLite("fund_misuse", "截留挪用",
                         "把 A 专项资金的支出挂到 B 项目账上",
                         "专项资金科目与用途不匹配"),
        OperatorSpecLite("bid_splitting", "规避招标",
                         "把 480 万合同拆成 3 份 160 万",
                         "单份金额恰好低于公开招标阈值 + 同一供应商同期多份"),
        OperatorSpecLite("overspend", "超标支出",
                         "把某笔三公经费改到标准线以上",
                         "支出标准表比对越界"),
        OperatorSpecLite("fund_stagnation", "资金滞留",
                         "把拨付日期向后推迟 N 个月",
                         "拨付与指标下达时间间隔超阈值"),
        OperatorSpecLite("fake_progress", "虚报进度",
                         "进度填 100% 但缺验收单",
                         "进度填报与验收材料不一致"),
        OperatorSpecLite("illegal_allowance", "违规发放",
                         "工资表插入一笔未经审批的津补贴",
                         "发放项无审批流 + 违反津补贴发放规定"),
        OperatorSpecLite("hidden_debt", "债务隐匿",
                         "把一笔融资移到表外主体",
                         "表外主体与本级政府存在资金往来 + 债务口径不匹配"),
    ],
    validator=("双闸门：A 资金流勾稽（预算指标数=下达数=拨付数=支出数=决算数，"
               "借贷平衡）；B 法规条款命中（违规事实 ↔ 公开法条库）。"
               "健康版全绿且零命中；埋雷版恰好命中预期的那一条（不多不少）。"),
    data_sources=[
        "审计署《审计结果公告》（公开，违规类型与表述语料）",
        "部门预算 / 决算公开数据（账套结构与金额分布先验）",
        "政府采购公告（招投标违规模式）",
        "公开法规库（预算法 / 政府采购法 / 财政违法行为处罚处分条例）",
        "⚠️ 真实审计底稿：不可用，仅可提取差分隐私聚合统计",
    ],
    compliance="绝不直接把真实审计数据做成公开数据集。照 FinancialAuditBench 路径："
               "只从真实数据提取差分隐私聚合统计作为合成器先验，产出全部合成。",
    mvp="GovAudit-Mini：1 个合成部门 × 1 年度 × 3 类算子 × 10 seed = 30 题 + 10 诱饵",
    status="planned",
)


# ---------------------------------------------------------------------------
# 赛道二：企业审计（内部审计 / 舞弊 / 内控）
# ---------------------------------------------------------------------------

CORP_AUDIT = AuditDomainSpec(
    key="corp-audit",
    name_cn="企业审计",
    name_en="Corporate / Internal Audit",
    hardness="L2",
    artifact="真实勾稽的制造业公司账套：总账 / 明细账 / 凭证附件 / 合同 / 银行流水 / 三大报表",
    operators=[
        OperatorSpecLite("premature_revenue", "收入提前确认",
                         "发货单在 12 月但签收单在次年 1 月仍确认收入",
                         "收入确认日早于风险报酬转移日（单证日期倒挂）"),
        OperatorSpecLite("expense_capitalization", "费用资本化",
                         "把管理费用重分类到在建工程",
                         "利润虚增 + 资产虚增 + 三表勾稽失衡"),
        OperatorSpecLite("under_provision", "少提减值",
                         "坏账准备计提比例 5% → 1%",
                         "减值率偏离历史 / 行业基准"),
        OperatorSpecLite("inventory_inflation", "存货虚增",
                         "账面数量 ≠ 盘点表数量",
                         "账实不符"),
        OperatorSpecLite("related_party_laundering", "关联交易非关联化",
                         "通过无关联过桥公司转手销售",
                         "资金流闭环 + 交易实质与法律形式背离"),
        OperatorSpecLite("round_tripping", "循环交易",
                         "A→B→C→A 走一圈虚增收入",
                         "收入增长与经营现金流增长背离"),
        OperatorSpecLite("sod_violation", "不相容职务未分离",
                         "同一人同时拥有申请与审批权限",
                         "权限矩阵冲突"),
        OperatorSpecLite("approval_gap", "审批链断裂",
                         "删除大额付款的二级审批记录",
                         "审批流节点缺失 / 金额越权"),
    ],
    validator=("三闸门，全确定性算术：A 三表勾稽（资产负债表平衡、现金流量表期末=货币资金、"
               "净利润→经营现金流调节表一致）；B 凭证链完整性（合同→发货→签收→发票→回款，"
               "五单齐全且日期单调）；C 红旗指标越界（Beneish M-Score / Altman Z / "
               "应收周转天数突变 / 毛利率偏离行业）。"),
    data_sources=[
        "上市公司公开财报 + XBRL（结构、科目、真实金额分布）",
        "SEC AAER / 证监会行政处罚决定（真实舞弊手法标注语料，金矿）",
        "行业财务比率基准（红旗指标阈值）",
        "⚠️ 企业真实账套：不可用，走合成 + 差分隐私先验",
    ],
    compliance="同国家审计：只取聚合先验，账套全部合成。",
    mvp="CorpAudit-Mini：合成制造业公司 × 1 年度 × 4 类算子 × 8 seed = 32 题 + 8 诱饵",
    status="planned",
)


# ---------------------------------------------------------------------------
# 赛道三：审计师（CPA / 工作底稿）
# ---------------------------------------------------------------------------

CPA_AUDIT = AuditDomainSpec(
    key="cpa-audit",
    name_cn="审计师",
    name_en="CPA / Audit Workpaper",
    hardness="L4",
    artifact="一份**正确完成**的审计工作底稿（含风险评估、程序、证据索引、结论）",
    operators=[
        OperatorSpecLite("procedure_omission", "程序遗漏",
                         "删掉对某一高风险认定的实质性程序",
                         "四段链中「程序」节点缺失"),
        OperatorSpecLite("sample_shortage", "样本不足",
                         "抽样规模 60 → 6",
                         "样本量低于准则/方法论要求"),
        OperatorSpecLite("evidence_broken", "证据断链",
                         "把结论引用的支持性文件从索引中移除",
                         "结论→证据索引指向不存在的文件"),
        OperatorSpecLite("contradict_conclusion", "结论与证据矛盾",
                         "证据显示存在差异但结论写「未发现异常」",
                         "结论文本与证据数值自相矛盾"),
        OperatorSpecLite("recompute_error", "计算错误",
                         "把重新计算（recomputation）的结果改错",
                         "底稿内算术不自洽"),
        OperatorSpecLite("date_inversion", "日期倒挂",
                         "审计报告日早于现场工作结束日",
                         "关键日期时序违规"),
        OperatorSpecLite("unapproved_change", "擅自变更程序",
                         "未经批准把函证改为替代程序",
                         "变更无审批记录"),
    ],
    validator=("三闸门（最难，判卷需人）：A 四段链可追溯（风险→程序→证据→结论，"
               "每段存在且指向一致，可自动检查）；B 持牌 CPA rubric（按任务类型设计，"
               "一次设计可复用于 N 个 seed）；C 复核模式 review——"
               "给一份「已完成」的底稿要求挑错（成本更低、区分度更高）。"),
    data_sources=[
        "中国注册会计师审计准则 / ISA（程序要求的形式化来源）",
        "事务所公开底稿模板（结构设计）",
        "FinancialAuditBench（MIT 开源，可直接参考其 rubric 结构与合成框架）",
        "⚠️ 真实工作底稿：不可用（保密 + 职业道德）",
    ],
    compliance="rubric 需持牌审计师投入（FinancialAuditBench 用了 1100+ 小时）。"
               "缓解：rubric 按任务类型复用，专家投入是一次性的。",
    mvp="CPAAudit-Mini：合成服务业公司 × 3 科目 × 5 类算子 × 6 seed = 30 题，半数 review 模式",
    status="planned",
)


# 已落地赛道（智能合约，L1）
CONTRACT_AUDIT = AuditDomainSpec(
    key="smart-contract",
    name_cn="智能合约审计",
    name_en="Smart Contract Audit",
    hardness="L1",
    artifact="健康的 Solidity 合约（功能测试全过、无已知漏洞）",
    operators=[
        OperatorSpecLite("reentrancy", "重入 SWC-107",
                         "把余额清零行从外部 call 前移到 require 后",
                         "健康版攻击失败 / 埋雷版攻击成功（Foundry 差分 PoC）"),
        OperatorSpecLite("access_control", "访问控制缺失 SWC-105",
                         "删除 onlyOwner 校验",
                         "非 owner 也能调用特权函数"),
        OperatorSpecLite("tx_origin", "tx.origin 鉴权 SWC-115",
                         "msg.sender → tx.origin",
                         "钓鱼合约可中继调用"),
        OperatorSpecLite("variation", "LLM 语义保持变体",
                         "改局部变量名 / 加注释 / 调序，漏洞位置行为不变",
                         "变体仍需过同一差分闸门"),
    ],
    validator="Foundry 差分：happy-path 全过 + 健康版攻击失败 + 埋雷版攻击成功，三条同时成立。",
    data_sources=["手写健康合约（src/）", "SWC Registry", "EVMbench / Code4rena 公开漏洞类型"],
    compliance="合成数据，无敏感性问题。",
    mvp="已有：3 算子 + 1 诱饵 + 变体，7 样本；目标扩到 100+",
    status="done",
)


DOMAIN_REGISTRY: Dict[str, AuditDomainSpec] = {
    d.key: d
    for d in (CONTRACT_AUDIT, CORP_AUDIT, GOV_AUDIT, CPA_AUDIT)
}


def get_domain(key: str) -> AuditDomainSpec:
    if key not in DOMAIN_REGISTRY:
        raise KeyError(f"未注册的赛道: {key}，可选 {list(DOMAIN_REGISTRY)}")
    return DOMAIN_REGISTRY[key]


def list_domains() -> List[AuditDomainSpec]:
    """按验证器硬度从低到高排列（L1 最易做，L4 最难做）。"""
    return sorted(DOMAIN_REGISTRY.values(), key=lambda d: d.hardness)


def scaffold_checklist(key: str) -> List[Tuple[str, str]]:
    """接入该赛道需要实现的类清单，供开发对照。"""
    d = get_domain(key)
    return [
        ("ArtifactGenerator", f"{d.name_cn}：产出 {d.artifact}"),
        ("IssueOperator", f"实现 {len(d.operators)} 个算子：" + "、".join(o.name_cn for o in d.operators)),
        ("IssueValidator", d.validator),
        ("ReportScorer", f"{d.hardness} 判卷口径，对齐 docs/04 表格"),
        ("HarborExporter", f"导出 {d.key}-* 任务集（mode=detect）"),
    ]
