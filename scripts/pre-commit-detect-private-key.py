"""Pre-commit hook: 检测私钥内容。"""

import re
import sys

PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")

exit_code = 0
for filepath in sys.argv[1:]:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if PRIVATE_KEY_PATTERN.search(content):
            print(f"错误：{filepath} 包含私钥内容。")
            exit_code = 1
    except OSError:
        pass
sys.exit(exit_code)
