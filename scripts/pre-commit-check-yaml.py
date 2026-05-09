"""Pre-commit hook: 检查 YAML 语法（支持多个文件）。"""

import sys

try:
    import yaml
except ImportError:
    print("缺少 yaml 模块，跳过检查。")
    sys.exit(0)

exit_code = 0
for filepath in sys.argv[1:]:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"错误：{filepath} YAML 解析失败：{exc}")
        exit_code = 1
    except OSError:
        pass
sys.exit(exit_code)
