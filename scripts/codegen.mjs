/** OpenAPI → TypeScript codegen runner。
 *
 * 用法：node scripts/codegen.mjs
 *
 * 依赖 uv 在 PATH 中可用（CI 上由 astral-sh/setup-uv 提供，本地由 uv
 * 自身保证）。export_openapi.py 通过 ``uv run python`` 执行，统一本地
 * Windows venv 与 CI ubuntu-latest 的入口路径。
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
console.log("Exporting OpenAPI JSON...");
run(`uv run python "${EXPORT_SCRIPT}"`);

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
