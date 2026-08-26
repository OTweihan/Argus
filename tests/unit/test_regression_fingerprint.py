"""回归指纹规范化与稳定性单元测试。"""

from __future__ import annotations

from argus_py.core.enums import FindingSeverity, FindingType, TaskType
from argus_py.regression.fingerprint import (
    FINGERPRINT_VERSION,
    compute_fingerprint,
    normalize_location,
    normalize_title,
)


def test_normalize_title_collapses_whitespace_and_case() -> None:
    assert normalize_title("  登录   失败 \n 提示异常 ") == "登录 失败 提示异常"
    assert normalize_title("Login FAILED") == "login failed"


def test_normalize_location_strips_line_suffixes() -> None:
    assert normalize_location("src/service/UserService.java:123") == "src/service/UserService.java"
    assert normalize_location("app.py:12-34") == "app.py"
    # 反复剥离：file.py:10:20 形式
    assert normalize_location("a/b/c.py:10:20") == "a/b/c.py"


def test_normalize_location_preserves_url_semantics() -> None:
    # URL 不剥行号（避免误伤端口），只去 fragment 与末尾斜杠
    assert normalize_location("http://host:8000/api/users#frag") == "http://host:8000/api/users"
    assert normalize_location("http://host:8000/api/users/") == "http://host:8000/api/users"
    assert normalize_location(None) == ""


def test_fingerprint_stable_and_discriminative() -> None:
    base = dict(
        task_type=TaskType.BLACKBOX,
        finding_type=FindingType.FUNCTIONAL,
        severity=FindingSeverity.HIGH,
        title="提交订单后金额显示错误",
        location="http://host/orders",
    )
    fp1 = compute_fingerprint(**base)
    fp2 = compute_fingerprint(**base)
    assert fp1 == fp2
    assert len(fp1) == 16

    # 标题首尾空白不影响指纹（strip 语义）
    assert compute_fingerprint(**{**base, "title": "  提交订单后金额显示错误 "}) == fp1
    # 大小写归一：英文标题大小写差异不影响指纹
    en = dict(base, title="Login FAILED")
    assert compute_fingerprint(**en) == compute_fingerprint(**{**en, "title": "login failed"})

    # severity 变化 → 不同指纹
    assert compute_fingerprint(**{**base, "severity": FindingSeverity.CRITICAL}) != fp1
    # task_type 参与指纹（黑白盒同类问题不混同）
    assert compute_fingerprint(**{**base, "task_type": TaskType.WHITEBOX}) != fp1


def test_fingerprint_version_constant() -> None:
    assert FINGERPRINT_VERSION == "v1"
