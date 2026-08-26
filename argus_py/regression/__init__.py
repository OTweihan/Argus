"""项目级回归测试闭环。

模块职责：
- ``enums``：回归用例/批次/批次项状态机枚举；
- ``models``：RegressionCase / RegressionRun / RegressionRunItem 领域模型；
- ``fingerprint``：问题稳定指纹（跨批次比较键）；
- ``diff``：相对基线的差异计算与固定质量门禁判定（纯函数）；
- ``application``：批次协调、终态推进、基线管理与崩溃恢复编排。

存储位于 ``argus_py.task.repositories.regression_repo``，经
``TaskSQLiteStorage`` facade 暴露（与 correlation 相同的分层方式）。
"""
