/** OpenAPI → TypeScript codegen runner。
 *
 * 用法：node scripts/codegen.mjs
 *
 * 依赖 uv 在 PATH 中可用（CI 上由 astral-sh/setup-uv 提供，本地由 uv
 * 自身保证）。export_openapi.py 通过 ``uv run python`` 执行，统一本地
 * Windows venv 与 CI ubuntu-latest 的入口路径。
 *
 * 注意：必须使用 ``uv run --no-sync``。uv 的 ``uv run`` 默认会先执行隐式
 * ``uv sync``，在本地 venv 正在被运行中的应用占用（如 cryptography 的
 * ``_rust.pyd`` 被锁）时会导致同步失败并中断导出，与项目"启动脚本不得
 * 隐式执行 uv sync"的约定一致。CI 中 codegen 前已显式 ``uv sync --frozen``，
 * 因此 ``--no-sync`` 不会跳过任何必需的依赖安装。
 */

import { execSync } from "node:child_process";
import { existsSync, unlinkSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const _HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(_HERE, "..");
const EXPORT_SCRIPT = resolve(_HERE, "export_openapi.py");
const OPENAPI_JSON = resolve(ROOT, "openapi.json");
const FRONTEND = resolve(ROOT, "frontend");
const OUTPUT = resolve(FRONTEND, "src/api/openapi.gen.ts");

function run(cmd, opts = {}) {
  console.log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", ...opts });
}

// Step 1: Export OpenAPI JSON via uv (works on Windows and Linux)
// --no-sync：避免 uv run 触发隐式 uv sync（本地 venv 被占用时会中断导出）
console.log("Exporting OpenAPI JSON...");
run(`uv run --no-sync python "${EXPORT_SCRIPT}"`);

if (!existsSync(OPENAPI_JSON)) {
  console.error("openapi.json not found — export failed");
  process.exit(1);
}

// Step 2: Generate TypeScript types (npx 自动处理 Windows .cmd / Unix symlink)
console.log("Generating TypeScript types...");
run(`npx -y openapi-typescript "${OPENAPI_JSON}" -o "${OUTPUT}"`, { cwd: FRONTEND });

// Step 3: Clean up
console.log("Cleaning up openapi.json...");
unlinkSync(OPENAPI_JSON);

console.log("Codegen complete.");
