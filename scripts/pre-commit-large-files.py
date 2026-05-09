"""Pre-commit hook: 检查新增文件是否超过大小限制（默认 2MB）。"""

import sys

MAX_KB = 2048

for filepath in sys.argv[1:]:
    try:
        with open(filepath, "rb") as f:
            size = f.seek(0, 2)
        if size > MAX_KB * 1024:
            print(f"错误：{filepath} 大小为 {size / 1024:.1f}KB，超过 {MAX_KB}KB 限制。")
            sys.exit(1)
    except OSError:
        pass
sys.exit(0)
