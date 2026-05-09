"""pre-commit hook：阻止敏感文件被提交到 Git。

拦截规则：
  - config/llm.env / config/llm.local.env — API 密钥文件
  - config/.fernet_key — 加密密钥
  - config/browser-states/*.json — 浏览器会话（含 cookie/token）

使用方式（配合 .pre-commit-config.yaml）：
  pre-commit install
"""

import sys

SENSITIVE_EXACT = {
    "config/llm.env",
    "config/llm.local.env",
    "config/.fernet_key",
}

SENSITIVE_PREFIXES = {
    "config/browser-states/",
}

EXIT_CODE = 0


def check_file(filepath: str) -> None:
    normalized = filepath.replace("\\", "/")
    if normalized in SENSITIVE_EXACT:
        print(
            f"  ✗ {filepath}: 此文件包含敏感凭据，禁止提交。\n"
            f"    → 使用 git restore --staged {filepath} 移出暂存区"
        )
        global EXIT_CODE
        EXIT_CODE = 1
        return
    for prefix in SENSITIVE_PREFIXES:
        if normalized.startswith(prefix) and normalized.endswith(".json"):
            print(
                f"  ✗ {filepath}: 浏览器状态文件包含会话凭据，禁止提交。\n"
                f"    → 使用 git restore --staged {filepath} 移出暂存区"
            )
            EXIT_CODE = 1
            return


def main() -> None:
    for filepath in sys.argv[1:]:
        check_file(filepath)
    sys.exit(EXIT_CODE)


if __name__ == "__main__":
    main()
