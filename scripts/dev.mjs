#!/usr/bin/env node

/**
 * Argus 跨平台开发进程管理器。
 *
 * 同时启动 Python API、Vite 前端和 Java Analyzer，并聚合、持久化三路日志。
 * 仅使用 Node.js 内置模块，支持 Windows、macOS 和 Linux。
 */

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const MIN_NODE_MAJOR = 20;
const STARTUP_TIMEOUT_MS = 60_000;
const GRACEFUL_SHUTDOWN_MS = 5_000;
const isWindows = process.platform === "win32";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "..");

const paths = {
  uvLock: path.join(projectRoot, "uv.lock"),
  venvConfig: path.join(projectRoot, ".venv", "pyvenv.cfg"),
  python: path.join(
    projectRoot,
    ".venv",
    isWindows ? path.join("Scripts", "python.exe") : path.join("bin", "python"),
  ),
  frontend: path.join(projectRoot, "frontend"),
  frontendModules: path.join(projectRoot, "frontend", "node_modules"),
  javaPom: path.join(projectRoot, "java_analyzer", "pom.xml"),
};

const serviceDefinitions = [
  {
    name: "python",
    color: "\u001b[36m",
    cwd: projectRoot,
    command: () => paths.python,
    args: [
      "-u",
      "-m",
      "argus_py.cli.main",
      "serve",
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
      "--reload",
    ],
    healthUrl: "http://127.0.0.1:8000/health",
  },
  {
    name: "frontend",
    color: "\u001b[35m",
    cwd: paths.frontend,
    command: (tools) => tools.pnpm,
    args: ["dev"],
    healthUrl: "http://127.0.0.1:5173/",
  },
  {
    name: "java",
    color: "\u001b[33m",
    cwd: projectRoot,
    command: (tools) => tools.maven,
    args: ["-f", paths.javaPom, "spring-boot:run"],
    healthUrl: "http://127.0.0.1:8081/actuator/health",
  },
];

const RESET_COLOR = "\u001b[0m";
const ERROR_COLOR = "\u001b[31m";
const SUCCESS_COLOR = "\u001b[32m";
const DIM_COLOR = "\u001b[90m";
const ANSI_PATTERN =
  /[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d\/#&.:=?%@~_]+)*)?\u0007)|(?:(?:\d{1,4}(?:[;:]\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g;

let tools = null;
let shuttingDown = false;
let shutdownPromise = null;
let combinedLog = null;
const serviceLogs = new Map();
const children = [];
let rejectUnexpectedExit = null;

function print(message, color = "") {
  if (process.stdout.isTTY && color) {
    process.stdout.write(`${color}${message}${RESET_COLOR}\n`);
  } else {
    process.stdout.write(`${message}\n`);
  }
}

function printError(message) {
  if (process.stderr.isTTY) {
    process.stderr.write(`${ERROR_COLOR}${message}${RESET_COLOR}\n`);
  } else {
    process.stderr.write(`${message}\n`);
  }
}

function showHelp() {
  print("用法：node scripts/dev.mjs [--check]");
  print("");
  print("  默认       启动 Python、前端和 Java，并聚合日志");
  print("  --check    只检查本地环境与端口，不启动服务");
  print("  --help     显示此帮助");
}

function parseArguments(argv) {
  const known = new Set(["--check", "--help", "-h"]);
  const unknown = argv.filter((arg) => !known.has(arg));
  if (unknown.length > 0) {
    throw new Error(`不支持的参数：${unknown.join(", ")}`);
  }
  return {
    checkOnly: argv.includes("--check"),
    help: argv.includes("--help") || argv.includes("-h"),
  };
}

function findExecutable(name) {
  const locator = isWindows ? "where.exe" : "which";
  const result = spawnSync(locator, [name], {
    cwd: projectRoot,
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) {
    return null;
  }
  const candidates = result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (isWindows) {
    return candidates.find((candidate) => /\.(?:exe|com|cmd|bat)$/i.test(candidate)) ?? null;
  }
  return candidates[0] ?? null;
}

function runVersionCheck(command, args) {
  const invocation = prepareInvocation(command, args);
  const result = spawnSync(invocation.command, invocation.args, {
    cwd: projectRoot,
    encoding: "utf8",
    windowsHide: true,
    shell: invocation.shell,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
    },
  });
  return {
    ok: result.status === 0,
    output: `${result.stdout ?? ""}\n${result.stderr ?? ""}`.trim(),
  };
}

function quoteForCmd(value) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function prepareInvocation(command, args) {
  if (isWindows && /\.(?:cmd|bat)$/i.test(command)) {
    const commandLine = [quoteForCmd(command), ...args.map(quoteForCmd)].join(" ");
    return {
      command: commandLine,
      shell: process.env.ComSpec || true,
    };
  }
  return { command, args, shell: false };
}

function assertFile(filePath, message) {
  if (!fs.existsSync(filePath)) {
    throw new Error(message);
  }
}

function checkPortAvailable(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", (error) => {
      if (error.code === "EADDRINUSE" || error.code === "EACCES") {
        reject(new Error(`端口 ${port} 不可用，请先停止占用该端口的进程。`));
      } else {
        reject(error);
      }
    });
    server.listen({ host: "127.0.0.1", port, exclusive: true }, () => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
  });
}

async function runPreflight() {
  print("正在检查开发环境……", DIM_COLOR);

  const nodeMajor = Number.parseInt(process.versions.node.split(".")[0], 10);
  if (!Number.isInteger(nodeMajor) || nodeMajor < MIN_NODE_MAJOR) {
    throw new Error(`Node.js 版本过低：当前 ${process.versions.node}，需要 20 或更高版本。`);
  }

  assertFile(paths.uvLock, "缺少 uv.lock，无法确认 Python 锁定依赖。");
  assertFile(
    paths.venvConfig,
    "缺少 .venv/pyvenv.cfg，请执行：uv sync --frozen --extra browser --dev",
  );
  assertFile(
    paths.python,
    `当前平台缺少虚拟环境解释器 ${path.relative(projectRoot, paths.python)}。` +
      "如果 .venv 来自其他操作系统，请删除后执行：uv sync --frozen --extra browser --dev",
  );
  assertFile(
    paths.frontendModules,
    "缺少 frontend/node_modules，请执行：pnpm --dir frontend install --frozen-lockfile",
  );
  assertFile(paths.javaPom, "缺少 java_analyzer/pom.xml。");

  const venvConfig = fs.readFileSync(paths.venvConfig, "utf8");
  if (!/^uv\s*=\s*.+$/m.test(venvConfig)) {
    throw new Error(
      ".venv 不是可识别的 uv 管理环境，请重新执行：uv sync --frozen --extra browser --dev",
    );
  }

  const uv = findExecutable("uv");
  const pnpm = findExecutable("pnpm");
  const maven = findExecutable("mvn");
  if (!uv) {
    throw new Error("未找到 uv，请先安装 uv 并确保它位于 PATH 中。");
  }
  if (!pnpm) {
    throw new Error("未找到 pnpm，请先安装 pnpm 并确保它位于 PATH 中。");
  }
  if (!maven) {
    throw new Error("未找到 Maven，请先安装 mvn 并确保它位于 PATH 中。");
  }

  const uvVersion = runVersionCheck(uv, ["--version"]);
  if (!uvVersion.ok) {
    throw new Error(`uv 无法运行：${uvVersion.output}`);
  }
  const pythonVersion = runVersionCheck(paths.python, ["--version"]);
  if (!pythonVersion.ok) {
    throw new Error(`uv 虚拟环境中的 Python 无法运行：${pythonVersion.output}`);
  }
  const pythonMatch = pythonVersion.output.match(/Python\s+(\d+)\.(\d+)/i);
  if (!pythonMatch || Number(pythonMatch[1]) < 3 || (Number(pythonMatch[1]) === 3 && Number(pythonMatch[2]) < 11)) {
    throw new Error(`Python 版本不满足 >=3.11：${pythonVersion.output}`);
  }

  const pnpmVersion = runVersionCheck(pnpm, ["--version"]);
  if (!pnpmVersion.ok) {
    throw new Error(`pnpm 无法运行：${pnpmVersion.output}`);
  }
  const mavenVersion = runVersionCheck(maven, ["--version"]);
  if (!mavenVersion.ok) {
    throw new Error(`Maven 无法运行：${mavenVersion.output}`);
  }
  const javaMatch = mavenVersion.output.match(/Java version:\s*(\d+)/i);
  if (!javaMatch || Number(javaMatch[1]) < 21) {
    throw new Error(
      `Maven 必须使用 JDK 21 或更高版本。当前信息：\n${mavenVersion.output}`,
    );
  }

  await Promise.all([8000, 5173, 8081].map(checkPortAvailable));

  tools = { uv, pnpm, maven };
  print(`✓ Node.js ${process.versions.node}`, SUCCESS_COLOR);
  print(`✓ ${uvVersion.output.split(/\r?\n/)[0]}`, SUCCESS_COLOR);
  print(`✓ ${pythonVersion.output.split(/\r?\n/)[0]}（uv 虚拟环境）`, SUCCESS_COLOR);
  print(`✓ pnpm ${pnpmVersion.output.split(/\r?\n/)[0]}`, SUCCESS_COLOR);
  print(`✓ Maven/JDK 检查通过（JDK ${javaMatch[1]}）`, SUCCESS_COLOR);
  print("✓ 端口 8000、5173、8081 可用", SUCCESS_COLOR);
}

function timestampForDirectory(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    "-",
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join("");
}

function initializeLogs() {
  const logDir = path.join(
    projectRoot,
    "outputs",
    "logs",
    "dev",
    timestampForDirectory(new Date()),
  );
  fs.mkdirSync(logDir, { recursive: true });
  combinedLog = fs.createWriteStream(path.join(logDir, "combined.log"), { encoding: "utf8" });
  for (const definition of serviceDefinitions) {
    serviceLogs.set(
      definition.name,
      fs.createWriteStream(path.join(logDir, `${definition.name}.log`), { encoding: "utf8" }),
    );
  }
  return logDir;
}

function writeLog(service, channel, content, color = "") {
  const cleanContent = content.replace(ANSI_PATTERN, "");
  const line = `${new Date().toISOString()} [${service}][${channel}] ${cleanContent}`;
  combinedLog?.write(`${line}\n`);
  serviceLogs.get(service)?.write(`${line}\n`);

  const prefix = `[${service}][${channel}]`;
  if (process.stdout.isTTY && color) {
    process.stdout.write(`${color}${prefix}${RESET_COLOR} ${content}\n`);
  } else {
    process.stdout.write(`${prefix} ${content}\n`);
  }
}

function attachLineReader(stream, service, channel, color) {
  stream.setEncoding("utf8");
  let buffered = "";
  stream.on("data", (chunk) => {
    buffered += chunk;
    const lines = buffered.split(/\r\n|\n|\r/);
    buffered = lines.pop() ?? "";
    for (const line of lines) {
      if (line.length > 0) {
        writeLog(service, channel, line, color);
      }
    }
  });
  stream.on("end", () => {
    if (buffered.length > 0) {
      writeLog(service, channel, buffered, color);
      buffered = "";
    }
  });
}

function spawnService(definition) {
  const executable = definition.command(tools);
  // Windows 无法直接 CreateProcess .cmd/.bat；显式使用 cmd.exe，避免 shell:true
  // 在新 Node 版本中的参数拼接弃用告警。
  const invocation = prepareInvocation(executable, definition.args);

  const child = spawn(invocation.command, invocation.args ?? [], {
    cwd: definition.cwd,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONUNBUFFERED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
    detached: !isWindows,
    shell: invocation.shell,
    windowsHide: true,
  });

  const record = {
    definition,
    child,
    exited: false,
    exitPromise: null,
  };
  record.exitPromise = new Promise((resolve) => {
    child.once("close", (code, signal) => {
      record.exited = true;
      resolve({ code, signal });
      if (!shuttingDown) {
        rejectUnexpectedExit?.(
          new Error(
            `${definition.name} 服务意外退出（code=${code ?? "-"}, signal=${signal ?? "-"}）。`,
          ),
        );
      }
    });
  });

  child.once("error", (error) => {
    writeLog(definition.name, "stderr", `进程启动失败：${error.message}`, definition.color);
    if (!shuttingDown) {
      rejectUnexpectedExit?.(error);
    }
  });
  attachLineReader(child.stdout, definition.name, "stdout", definition.color);
  attachLineReader(child.stderr, definition.name, "stderr", definition.color);
  children.push(record);
  writeLog(definition.name, "supervisor", `已启动，PID=${child.pid}`, definition.color);
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForHealth(definition) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  let lastError = "尚未响应";

  while (!shuttingDown && Date.now() < deadline) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2_000);
      let response;
      try {
        response = await fetch(definition.healthUrl, {
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timer);
      }
      if (response.ok) {
        writeLog(
          definition.name,
          "supervisor",
          `服务已就绪：${definition.healthUrl}`,
          definition.color,
        );
        return;
      }
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error.message;
    }
    await delay(750);
  }

  throw new Error(
    `${definition.name} 服务未在 ${STARTUP_TIMEOUT_MS / 1000} 秒内就绪：${lastError}`,
  );
}

function signalProcessTree(record, force) {
  if (record.exited || !record.child.pid) {
    return;
  }
  try {
    if (isWindows) {
      const args = ["/PID", String(record.child.pid), "/T"];
      if (force) {
        args.push("/F");
      }
      spawnSync("taskkill.exe", args, { windowsHide: true, stdio: "ignore" });
    } else {
      process.kill(-record.child.pid, force ? "SIGKILL" : "SIGTERM");
    }
  } catch (error) {
    if (error.code !== "ESRCH") {
      writeLog(
        record.definition.name,
        "supervisor",
        `终止进程时出现问题：${error.message}`,
        record.definition.color,
      );
    }
  }
}

function closeStream(stream) {
  return new Promise((resolve) => {
    if (!stream || stream.closed) {
      resolve();
      return;
    }
    stream.end(resolve);
  });
}

async function shutdown(exitCode, reason) {
  if (shutdownPromise) {
    return shutdownPromise;
  }
  shuttingDown = true;
  shutdownPromise = (async () => {
    print(`\n${reason}`, exitCode === 0 || exitCode === 130 ? DIM_COLOR : ERROR_COLOR);
    for (const record of children) {
      signalProcessTree(record, false);
    }

    await Promise.race([
      Promise.allSettled(children.map((record) => record.exitPromise)),
      delay(GRACEFUL_SHUTDOWN_MS),
    ]);
    for (const record of children) {
      signalProcessTree(record, true);
    }
    await Promise.race([
      Promise.allSettled(children.map((record) => record.exitPromise)),
      delay(2_000),
    ]);
    for (const record of children) {
      if (!record.exited) {
        record.child.stdout?.destroy();
        record.child.stderr?.destroy();
        record.child.unref();
      }
    }

    await Promise.all([
      closeStream(combinedLog),
      ...[...serviceLogs.values()].map(closeStream),
    ]);
    process.exitCode = exitCode;
  })();
  return shutdownPromise;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    showHelp();
    return;
  }

  await runPreflight();
  if (options.checkOnly) {
    print("\n环境检查通过，未启动任何服务。", SUCCESS_COLOR);
    return;
  }

  const logDir = initializeLogs();
  print(`\n日志目录：${logDir}`, DIM_COLOR);
  print("日志可能包含敏感运行信息，请勿直接外传。", DIM_COLOR);
  print("按 Ctrl+C 停止全部服务。\n", DIM_COLOR);

  const unexpectedExit = new Promise((_, reject) => {
    rejectUnexpectedExit = reject;
  });
  for (const definition of serviceDefinitions) {
    spawnService(definition);
  }

  try {
    await Promise.race([
      Promise.all(serviceDefinitions.map(waitForHealth)),
      unexpectedExit,
    ]);
    print("\n全部服务已就绪。", SUCCESS_COLOR);
    print("前端：http://127.0.0.1:5173", SUCCESS_COLOR);
    print("API：http://127.0.0.1:8000/docs", SUCCESS_COLOR);
    await unexpectedExit;
  } catch (error) {
    if (!shuttingDown) {
      await shutdown(1, `开发环境异常：${error.message}`);
    }
  }
}

process.once("SIGINT", () => {
  void shutdown(130, "收到 Ctrl+C，正在停止全部服务……");
});
process.once("SIGTERM", () => {
  void shutdown(143, "收到终止信号，正在停止全部服务……");
});

try {
  await main();
} catch (error) {
  printError(`启动失败：${error.message}`);
  process.exitCode = 1;
}
