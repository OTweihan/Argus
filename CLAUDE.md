<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Argus** (4699 symbols, 10183 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Impact Analysis — MUST follow

- **Before editing any function/class/method**, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report blast radius + risk level to the user.
- **Before committing**, run `gitnexus_detect_changes()` to verify scope.
- **Do NOT proceed** if impact analysis returns HIGH or CRITICAL risk without user approval.
- **Do NOT rename symbols with find-and-replace** — use `gitnexus_rename` which understands the call graph.

## Context Queries

| Goal | Tool |
|------|------|
| Explore unfamiliar code | `gitnexus_query({query: "concept"})` — returns process-grouped results |
| Full symbol context (callers, callees, flows) | `gitnexus_context({name: "symbolName"})` |
| Codebase overview, index freshness | `gitnexus://repo/Argus/context` |
| All functional areas | `gitnexus://repo/Argus/clusters` |
| All execution flows | `gitnexus://repo/Argus/processes` |
| Step-by-step execution trace | `gitnexus://repo/Argus/process/{name}` |

## Skill Files

| Task | File |
|------|------|
| Architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Bug tracing / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tool/resource/schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| CLI: index, status, clean, wiki | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

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
