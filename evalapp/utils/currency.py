"""成本币种归一化 — 全链路美元（USD）口径的单点定义

2026-08 起生成器 trace 产物（execution_summary.jsonl /
execution_report_data.js）的成本字段由 cost_usd（美元）切换为
cost_cny（人民币），但评测报告链路统一以美元口径展示。

数据兼容：产物 / report_data.json 中仅有 cost_cny 时，
按固定汇率折算为美元，保证新旧工作区指标可直接对比。
"""

import os

# 美元 → 人民币固定折算汇率，可通过环境变量覆盖
USD_TO_CNY_RATE = float(os.environ.get("EVALAPP_USD_TO_CNY", "7.2"))


def cny_to_usd(value: float) -> float:
    """人民币金额折算为美元。"""
    return value / USD_TO_CNY_RATE


def extract_cost_usd(data: dict | None) -> float | None:
    """从字典中提取美元成本：优先 cost_usd，缺失时由 cost_cny 折算。

    非数值 / 缺失返回 None，调用方自行决定是否跳过。
    """
    if not isinstance(data, dict):
        return None
    usd = data.get("cost_usd")
    if isinstance(usd, (int, float)):
        return float(usd)
    cny = data.get("cost_cny")
    if isinstance(cny, (int, float)):
        return cny_to_usd(float(cny))
    return None
