"""Pre-commit hook: 检查 JSON 语法（支持多个文件）。"""

import json
import sys

exit_code = 0
for filepath in sys.argv[1:]:
    try:
        with open(filepath, encoding="utf-8") as f:
            json.load(f)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"错误：{filepath} JSON 解析失败：{exc}")
        exit_code = 1
sys.exit(exit_code)
