<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Argus** (5484 symbols, 11948 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/Argus/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Argus/clusters` | All functional areas |
| `gitnexus://repo/Argus/processes` | All execution flows |
| `gitnexus://repo/Argus/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Project Rules

## Environment

当前 Shell 环境为 bash（Windows 下通过 MSYS2 模拟），但本项目使用 Windows 原生 Python。运行 Python 命令时**必须**使用 venv 解释器路径，否则 uv 无法正确发现 Python 进程：

```bash
cd "D:/PythonProjects/Argus" && .venv/Scripts/python.exe -c "..."
```

或在 PowerShell 中先激活虚拟环境再执行：

```powershell
PS D:\PythonProjects\Argus> .\.venv\Scripts\Activate.ps1
PS D:\PythonProjects\Argus> python ...
```

## Logging

后端日志体系的约定、命名空间、handler 拆分、`audit()` / `log_event()` 用法、CLI 输出分层等说明，统一记录在 [docs/logging.md](docs/logging.md)。新增日志埋点或修改 [config/logging.yaml](config/logging.yaml) 前请先阅读。
