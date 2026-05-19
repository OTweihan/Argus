/** OpenAPI → TypeScript codegen runner。
 *
 * 用法：node scripts/codegen.mjs
 *
 * Windows 上 pnpm shell 脚本因 cmd.exe vs bash 语义不一致容易失败，
 * 本 script 用 child_process 确保跨平台一致。
 */

import { execSync } from "node:child_process";
import { existsSync, unlinkSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const _HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(_HERE, "..");
const PYTHON = resolve(ROOT, ".venv/Scripts/python.exe");
const EXPORT_SCRIPT = resolve(_HERE, "export_openapi.py");
const OPENAPI_JSON = resolve(ROOT, "openapi.json");
const FRONTEND = resolve(ROOT, "frontend");
const OUTPUT = resolve(FRONTEND, "src/api/openapi.gen.ts");

function run(cmd, opts = {}) {
  console.log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", ...opts });
}

// Step 1: Export OpenAPI JSON
console.log("Exporting OpenAPI JSON...");
run(`"${PYTHON}" "${EXPORT_SCRIPT}"`);

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
