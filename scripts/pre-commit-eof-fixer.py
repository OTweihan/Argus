"""Pre-commit hook: 确保文件以单个换行结尾（仅文本文件）。"""

import sys

exit_code = 0
for filepath in sys.argv[1:]:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if not content.endswith("\n"):
            content += "\n"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            exit_code = 1
    except OSError:
        pass
sys.exit(exit_code)
