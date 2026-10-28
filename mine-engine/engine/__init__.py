"""mine-engine · 动态对抗审计考试的注入漏洞引擎。

范式对齐 OpenDCAI/DataFlow（https://github.com/OpenDCAI/DataFlow）：
    Pipeline -> Operator -> (Prompt)
operator 处理一批结构化记录（list[dict]），可串联、可替换后端、可复现。

四个领域无关组件：
    generators  ArtifactGenerator  生成/加载健康基准体
    operators   IssueOperator      在种子程序上注入问题（注入漏洞）
    validators  IssueValidator     差分验证“雷确实存在、且没破坏材料”
    scorers     ReportScorer       把审计报告对 ground truth 判分
"""

__version__ = "0.1.0"
