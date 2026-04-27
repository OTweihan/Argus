# Argus 项目信息上下文

更新时间：2026-04-27

本文件用于后续接手 Argus 项目时快速恢复上下文。下次修改本项目之前，先阅读本文件，再阅读 `README.md` 和相关源码。

## 项目概览

Argus 是一个面向 Web 应用质量保障场景的 AI Native 测试平台。第一阶段目标是黑盒 MVP：通过 CLI 输入自然语言任务，调用大模型规划动作，驱动浏览器执行，并输出结构化报告。

当前项目路径：

```text
D:\PythonProjects\Argus
```

主要技术栈：

- Python 3.11+
- Playwright Python
- OpenAI Chat Completions 兼容大模型接口
- Jinja2 HTML 报告
- JSON / 文件系统作为 MVP 阶段存储边界

## 当前阶段

当前已推进到 T003 附近：

- T001 项目骨架：已完成基础目录、模型、CLI、配置、报告、占位模块。
- T002 浏览器封装：已完成 Playwright 生命周期、浏览器动作、页面快照、CLI 调试入口。
- T003 LLM 调用模块：已完成 OpenAI 兼容调用、响应模型、JSON 解析、Prompt 模板、重试封装、LLM 配置命令。

完整黑盒 Agent 执行闭环尚未完成，`argus run` 当前只创建任务并保存初始任务文件。

## 关键命令

安装开发模式：

```powershell
pip install -e ".[dev]"
```

配置大模型：

```powershell
argus config llm
```

检查大模型连接：

```powershell
argus llm check
```

检查浏览器能力：

```powershell
argus browser check --url "https://httpbin.org"
```

显示浏览器窗口：

```powershell
argus browser check --url "https://httpbin.org" --headed
```

## 近期重要变更

### CLI

入口文件：`argus_py/cli/main.py`

- 增加 `argus browser check`，用于调试浏览器打开页面、截图、点击、输入等能力。
- 增加 `argus config llm`，用于交互式配置大模型 API，不要求用户手动编辑配置文件。
- 增加 API Key 星号掩码输入。
- 首次配置只提示 API Key、接口地址、模型名称；高级参数通过 `--advanced` 调整。
- 交互提示文案抽到 `argus_py/cli/messages.py`。
- `argus llm check` 改成固定低消耗连接检查，不再允许用户自由输入 Prompt。
- `argus llm check` 内部固定使用 `config/prompts/llm_connection_check.md`，最大输出 Token 数为 4，温度为 0。
- `argus llm check` 连接检查不走配置里的重试次数，当前为零重试，避免失败时长时间等待和重复消耗。

### 配置

系统配置与大模型配置已拆分：

- 系统配置模块：`argus_py/config/settings.py`
- 大模型配置模块：`argus_py/config/llm_settings.py`
- 大模型真实配置文件：`config/llm.env`
- 大模型配置模板：`config/llm.env.example`

注意：

- `config/llm.env` 包含敏感信息，已加入 `.gitignore`，不要提交、输出或复制其中内容。
- 顶层 `config` 目录只作为数据配置目录使用，不再放 Python 模块。
- 之前存在过 `config/settings.py`、`config/llm_settings.py`，容易和 `argus_py.config` 混淆，已删除。

### 路径解析

新增统一路径模块：`argus_py/core/paths.py`

当前统一管理：

- 项目根目录
- `config` 目录
- Prompt 目录
- LLM env 文件
- `outputs` 目录
- 报告模板目录

目的：

- 避免从非项目根目录执行 `argus` 时找不到配置、Prompt、报告模板或输出目录。
- 支持环境变量 `ARGUS_PROJECT_ROOT` 覆盖项目根目录。

### 浏览器封装

主要文件：

- `argus_py/browser/playwright_client.py`
- `argus_py/browser/base.py`
- `argus_py/browser/actions.py`
- `argus_py/browser/selectors.py`
- `argus_py/browser/snapshot.py`

已完成：

- Playwright 启停、Context、Page 管理。
- 浏览器动作封装：打开页面、点击、输入、按键、下拉选择、等待、截图、快照。
- 页面稳定等待：`domcontentloaded`、`load`、`readyState`、`networkidle`、额外 settle。
- 对 SPA、长连接、埋点页面放宽等待策略：`load` 或 `networkidle` 超时不再直接阻断截图和快照。
- `BrowserSession.stop()` 已加固，即使关闭 Context 失败，也会继续释放 Playwright Client，降低浏览器进程残留风险。

### LLM 模块

主要文件：

- `argus_py/llm/client.py`
- `argus_py/llm/models.py`
- `argus_py/llm/prompts.py`
- `argus_py/llm/parser.py`
- `argus_py/llm/retry.py`

已完成：

- OpenAI Chat Completions 兼容请求。
- 请求 / 响应数据模型。
- JSON 响应提取与必填字段校验。
- Prompt 模板加载。
- 异步重试逻辑。
- API Key 缺失提示已改为面向用户：提示执行 `argus config llm`。

## 已知问题

1. `argus run` 还没有真正执行浏览器动作闭环。
   当前只创建任务并提示完整闭环将在后续实现。

2. T003 验收里的 JSON 解析能力已有代码，但 CLI 连接检查不再暴露自由 Prompt。
   后续可以新增固定 Prompt 的 `argus llm json-check`，既验证 JSON 解析，又避免用户自由输入导致 token 消耗不可控。

3. Prompt 模板当前放在 `config/prompts`。
   这适合源码项目本地运行；如果未来打包成 wheel 并在任意目录安装，需要考虑把内置 Prompt 放入包内资源，再允许外部配置覆盖。

4. 当前存在大量未提交变更。
   修改前应先用 `git status --short` 看清楚工作区状态，不要回退用户已有改动。

5. `config` 目录下可能还残留 `__pycache__`。
   这不是源码问题，后续可在用户确认后清理；不要擅自删除。

6. 浏览器 CLI 仍是轻量调试入口，不是完整测试执行器。
   它适合验证打开页面、截图、输入、点击是否可用。

7. LLM 网络问题需要区分代码问题和代理 / TLS / 服务问题。
   之前出现过请求卡在 TLS/代理握手阶段，已给 `argus llm check` 加超时和 Ctrl+C 友好处理。

## 待办清单

### 高优先级

- 实现 T005 黑盒 Runner：串联任务、规划、浏览器动作、观察、评估、报告。
- 将 `BlackboxPlanner` 接入 LLM，输出结构化动作序列。
- 将 `BlackboxEvaluator` 接入 LLM，判断目标是否完成和是否发现问题。
- 增加固定低消耗 JSON 检查命令，例如 `argus llm json-check`。
- 给 `argus browser check` 增加更友好的元素定位说明或自动列出候选交互元素。

### 中优先级

- 报告生成接入任务执行结果。
- 任务存储从临时 JSON 文件逐步演进到 SQLite + 文件系统。
- 给浏览器动作错误增加更多上下文，比如当前 URL、页面标题、候选元素数量。
- 为 CLI 错误输出统一格式。
- 将路径、配置、LLM、浏览器封装补充单元测试。

### 低优先级

- 清理历史 `__pycache__`、临时文件和过时占位内容。
- 完善 README 的阶段说明和开发命令。
- 考虑将 Prompt 模板区分为内置模板和用户模板。
- 后续如果进入 Web API 阶段，再补 FastAPI 项目结构和接口约定。

## 下次接手建议流程

1. 先阅读本文件。
2. 执行只读检查：

```powershell
git -C "D:\PythonProjects\Argus" status --short
```

3. 阅读本次要改的相关模块，不要直接按记忆修改。
4. 不要输出 `config/llm.env` 内容。
5. 不要主动运行编译、测试、真实 LLM 调用或浏览器命令，除非用户明确要求。
6. 如果需要验证 CLI 参数，只运行 `--help` 这类非联网、非真实执行命令。

## 重点文件索引

```text
README.md
argus_py/cli/main.py
argus_py/cli/messages.py
argus_py/core/paths.py
argus_py/core/constants.py
argus_py/config/settings.py
argus_py/config/llm_settings.py
argus_py/llm/client.py
argus_py/llm/models.py
argus_py/llm/prompts.py
argus_py/llm/parser.py
argus_py/llm/retry.py
argus_py/browser/playwright_client.py
argus_py/browser/base.py
argus_py/browser/actions.py
argus_py/browser/selectors.py
argus_py/browser/snapshot.py
argus_py/blackbox/planner.py
argus_py/blackbox/evaluator.py
argus_py/blackbox/runner.py
argus_py/task/service.py
argus_py/task/storage.py
argus_py/report/html_report.py
config/prompts/llm_connection_check.md
config/llm.env.example
```
