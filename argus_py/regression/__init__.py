"""项目级回归测试闭环。

模块职责：

- ``enums``：回归用例/批次/批次项状态机枚举；
- ``models``：RegressionCase / RegressionRun / RegressionRunItem 领域模型；
- ``fingerprint``：问题稳定指纹（跨批次比较键）；
- ``diff``：相对基线的差异计算与固定质量门禁判定（纯函数）；
- ``application``：对外门面 ``RegressionService`` / ``RegressionError`` /
  ``REGRESSION_PARAMS_KEY``（基线/查询 + Mixin 组合）；
- ``case_commands`` / ``run_commands`` / ``run_finalization`` / ``run_recovery``：
  按生命周期切开的内部 Mixin（可维护性 M3；请勿单独实例化）；
- ``_common``：包内共享常量、状态映射与错误类型定义；
- ``_deps``：``RegressionServiceDeps`` Protocol（内部类型面）。

存储位于 ``argus_py.task.repositories.regression_repo``，经
``TaskSQLiteStorage`` facade 暴露（与 correlation 相同的分层方式）。

**对外 import**::

    from argus_py.regression.application import (
        REGRESSION_PARAMS_KEY,
        RegressionError,
        RegressionService,
    )
"""
