"""Pre-commit hook: 检查合并冲突标记。"""

import re
import sys

CONFLICT_PATTERN = re.compile(r"<<<<<<< |=======$|>>>>>>> ")

exit_code = 0
for filepath in sys.argv[1:]:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if CONFLICT_PATTERN.search(content):
            print(f"错误：{filepath} 包含合并冲突标记。")
            exit_code = 1
    except OSError:
        pass
sys.exit(exit_code)
