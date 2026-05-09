"""Pre-commit hook: 移除行尾空白。"""

import sys

exit_code = 0
for filepath in sys.argv[1:]:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        new_lines = []
        modified = False
        for line in content.splitlines(True):
            stripped = line.rstrip(" \t\r\n")
            new_line = stripped + "\n"
            if new_line != line:
                modified = True
            new_lines.append(new_line)
        if modified:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            exit_code = 1
    except OSError:
        pass
sys.exit(exit_code)
