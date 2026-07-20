"""导出 FastAPI OpenAPI JSON 供前端 openapi-typescript codegen 使用。

用法：python scripts/export_openapi.py [--output openapi.json]

--output 默认写入项目根目录的 openapi.json，
前端 codegen 脚本消费后应删除此中间文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent


def main() -> None:
    output = _parse_args()

    sys.path.insert(0, str(_PROJECT_ROOT))

    from argus_py.api.app import create_app

    app = create_app()
    openapi_schema = app.openapi()

    output.write_text(
        json.dumps(openapi_schema, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OpenAPI JSON exported: {output} ({len(json.dumps(openapi_schema))} bytes)")


def _parse_args() -> Path:
    parser = argparse.ArgumentParser(description="导出 FastAPI OpenAPI JSON 架构")
    default = _PROJECT_ROOT / "openapi.json"
    parser.add_argument(
        "--output",
        type=Path,
        default=default,
        help=f"输出文件路径（默认：{default}）",
    )
    args = parser.parse_args()
    return args.output


if __name__ == "__main__":
    main()
