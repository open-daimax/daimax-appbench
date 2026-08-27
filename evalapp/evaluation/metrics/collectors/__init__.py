"""原始数据采集器 —— 跑工具 / 解析日志 / 调用 AI，产出供维度评分的原始数据。

- aesthetics:   AI 美观度评分调用（截图 → 视觉模型评分）
- code_quality: lint / 圈复杂度 / 重复度静态采集
- device_logs:  设备日志解析（crash / ANR 事件提取）
"""
