# Argus 项目信息上下文

更新时间：2026-04-29

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

当前已推进到 T007：

- T001 项目骨架：已完成基础目录、模型、CLI、配置、报告、占位模块。
- T002 浏览器封装：已完成 Playwright 生命周期、浏览器动作、页面快照、CLI 调试入口。
- T003 LLM 调用模块：已完成 OpenAI 兼容调用、响应模型、JSON 解析、Prompt 模板、重试封装、LLM 配置命令。
- T004 任务模型与执行边界：已完成任务 JSON 反序列化、文件存储读取、任务查询、状态流转、步骤日志、问题记录和可注册任务执行器。
- T005 黑盒 Agent 主逻辑：已完成 LLM 动作规划、浏览器动作执行、页面快照观察、LLM 结果评估、步骤日志和问题记录闭环。
- T006 报告生成：已完成 HTML/JSON 报告生成、截图相对路径展示、任务完成/失败后报告路径回写。
- T007 CLI 端到端联调：已完成 `argus run` 接入任务创建、黑盒执行、失败恢复、每步截图、报告输出和失败状态回写。

`argus run` 当前会真实执行黑盒闭环。需要只创建任务时使用 `--create-only`。

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

保存浏览器登录态：

```powershell
argus auth save --url "https://example.com/login"
```

复用登录态执行任务：

```powershell
argus run --auth-state example.com --goal "检查个人中心页面是否正常展示" --url "https://example.com/profile"
```

执行黑盒任务：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org"
```

只创建任务快照：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org" --create-only
```

关闭步骤截图：

```powershell
argus run --goal "打开页面并检查标题" --url "https://httpbin.org" --no-screenshot
```

T007 报告默认输出到：

```text
outputs/reports/<task_id>/index.html
outputs/reports/<task_id>/report.json
```

步骤截图默认输出到：

```text
outputs/screenshots/<task_id>/
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
- `argus llm check` 内部固定使用 `llm_connection_check.md` 模板，最大输出 Token 数为 4，温度为 0。
- `argus llm check` 连接检查不走配置里的重试次数，当前为零重试，避免失败时长时间等待和重复消耗。
- `argus run` 已接入 `TaskRunner` 和 `BlackboxRunner`，默认 headless 执行；可用 `--headed` 显示浏览器窗口。
- `argus run --create-only` 保留只创建任务快照的旧行为。
- `argus auth save --url <登录页>` 会打开可视化浏览器，等待用户完成登录后把 Playwright `storage_state` 保存到 `config/browser-states/<域名>.json`；也可以用 `--name <名称>` 自定义名称。
- 带端口的登录 URL 会把端口冒号转换为文件名安全的 `-`，例如 `10.18.90.80:8580` 保存为 `config/browser-states/10.18.90.80-8580.json`。
- `argus auth list` 会列出已保存登录态，显示名称、关联站点、修改时间、复用命令和路径；不会打印 Cookie 内容。
- `argus run --auth-state <名称或路径>` 会在新浏览器上下文中加载已保存登录态，减少重复登录。
- `argus run` 的 `--max-steps` 和 `--timeout` 为可选参数，用户不传时系统会通过任务策略模块按任务描述自动分配。
- `argus run` 的 `--max-steps` 和 `--timeout` 接受正整数；非法值会在参数解析阶段拦截。
- `argus run --browser` 和 `argus browser check --browser` 限制为 `chromium`、`firefox`、`webkit`。
- `argus run --no-screenshot` 会关闭执行步骤截图；即使 LLM 输出 `screenshot` 动作，也只记录跳过，不落图。
- CLI 运行期错误统一输出为 `错误：...`、`详情：...`、`提示：...` 格式；取消类输出统一为 `已取消：...`。

### 任务执行策略

主要文件：

- `argus_py/task/strategy.py`

当前行为：

- `resolve_execution_limits()` 统一合并用户显式传入的最大步数 / 超时时间和系统推断值。
- `infer_execution_limits()` 根据任务目标和 URL 推断简单、普通、复杂任务的默认限制。
- 该模块不依赖 CLI，可供后续 Web API 或任务服务复用。

### 黑盒 Agent

主要文件：

- `argus_py/blackbox/planner.py`
- `argus_py/blackbox/evaluator.py`
- `argus_py/blackbox/runner.py`
- `argus_py/llm/prompts/blackbox_planner.md`
- `argus_py/llm/prompts/blackbox_evaluator.md`
- `config/prompts/blackbox_planner.md`（用户覆盖模板）
- `config/prompts/blackbox_evaluator.md`（用户覆盖模板）

当前行为：

- 初始规划只确定性执行 `goto` 起始 URL；初始截图由 `goto` 步骤的自动证据采集负责，不再额外插入独立 `screenshot` 步骤。
- 后续规划由 LLM 根据用户目标、当前 URL、页面快照和历史步骤生成。
- 每个动作执行后统一采集步骤证据：截图路径和页面快照；截图失败或快照失败不会直接覆盖动作结果。
- 传给 LLM 的 history 会包含 `screenshot_path`，让评估器和规划器知道自动截图证据已采集，避免“打开页面并截图”这类目标在 `goto` 后再重复规划独立 `screenshot` 步骤。
- 动作失败会记录失败步骤，并尽量截图；随后重新观察页面，让规划器基于失败历史重新规划，默认最多恢复 2 次。
- 评估器根据目标、历史和最新观察判断是否完成。对登录页、表单页、流程类任务，不允许只因元素存在就判定完成，必须看到实际交互证据。
- 对新增、创建、添加、录入类任务，不能只因打开表单或观察到必填校验就判定完成；需要尽量覆盖新增入口、关键字段、必填校验、无效格式或边界数据、取消/关闭等低风险场景，且避免创建真实业务数据。
- 完成时 `reason` 应说明已覆盖的测试场景，例如页面打开、空表单提交、无效账号提交、错误提示或状态变化。

### 选择器与页面快照

主要文件：

- `argus_py/browser/selectors.py`
- `argus_py/browser/snapshot.py`

当前行为：

- 页面快照会列出可交互元素，并提供推荐 selector。
- 输入框优先推荐稳定定位，例如 `css=[name="username"]`、`css=#id`、`css=input[type="password"]`。
- 按钮和链接优先推荐 ARIA role 定位，例如 `role=button[name="登录"]`、`role=link[name="提交"]`。
- 选择器解析层兼容常见 LLM 误写：
  - `button:contains("登录")` 转换为 `role=button[name="登录"]`
  - `a:contains("提交")` 转换为 `role=link[name="提交"]`
  - `selector=role=button[name="登录"]` 会自动去掉 `selector=` 前缀
- Planner Prompt 要求优先使用页面快照中的 `selector=` 推荐值；如果历史中某 selector 执行失败，不要重复使用同一个 selector。

### 配置

系统配置与大模型配置已拆分：

- 系统配置模块：`argus_py/config/settings.py`
- 大模型配置模块：`argus_py/config/llm_settings.py`
- 大模型真实配置文件：`config/llm.env`
- 大模型配置模板：`config/llm.env.example`

注意：

- `config/llm.env` 包含敏感信息，已加入 `.gitignore`，不要提交、输出或复制其中内容。
- `config/browser-states/*.json` 包含 Cookie、LocalStorage 等会话信息，已加入 `.gitignore`，不要提交、输出或复制其中内容。
- 顶层 `config` 目录只作为数据配置目录使用，不再放 Python 模块。
- 之前存在过 `config/settings.py`、`config/llm_settings.py`，容易和 `argus_py.config` 混淆，已删除。

### 路径解析

新增统一路径模块：`argus_py/core/paths.py`

当前统一管理：

- 项目根目录
- `config` 目录
- Prompt 目录
- 浏览器登录态目录
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
- 页面快照已增强 selector 推荐，降低 LLM 生成不可用 CSS 的概率。
- 选择器解析兼容部分 jQuery 风格 `:contains()` 误写。

### LLM 模块

主要文件：

- `argus_py/llm/client.py`
- `argus_py/llm/models.py`
- `argus_py/llm/prompts.py`
- `argus_py/llm/prompts/llm_connection_check.md`
- `argus_py/llm/prompts/blackbox_planner.md`
- `argus_py/llm/prompts/blackbox_evaluator.md`
- `argus_py/llm/parser.py`
- `argus_py/llm/retry.py`

已完成：

- OpenAI Chat Completions 兼容请求。
- 请求 / 响应数据模型。
- JSON 响应提取与必填字段校验。
- Prompt 模板加载。
- 异步重试逻辑。
- API Key 缺失提示已改为面向用户：提示执行 `argus config llm`。
- Prompt 模板已区分内置模板和用户覆盖模板：显式路径 > `config/prompts` 用户模板 > `argus_py/llm/prompts` 内置模板。
- 内置 Prompt 已加入包数据，后续安装包运行时不依赖源码目录下的 `config/prompts`。

### T007 文档与示例

主要文件：

- `README.md`
- `examples/README.md`
- `examples/task_001_screenshot.json`
- `examples/task_002_multistep.json`

已完成：

- README 已补齐 CLI 常用命令速查、示例任务说明和 T007 报告产物说明。
- 示例任务 JSON 已同步为当前 `Task` 模型字段：`start_url`、`max_steps`、`timeout_seconds`、`capture_screenshots`。
- `examples/README.md` 已说明示例 JSON 与 `argus run` CLI 参数的关系。
- 当前 CLI 不直接读取示例 JSON；示例文件用于说明任务模型结构。

### 报告阅读体验

主要文件：

- `argus_py/report/templates/base.html.j2`
- `argus_py/report/templates/blackbox_report.html.j2`

已完成：

- 报告顶部增加失败步骤数量，执行步骤区增加失败步骤聚合摘要。
- 步骤参数改为默认折叠，减少长 JSON 参数占用页面空间。
- 步骤截图和问题截图改为默认折叠，复杂任务报告更容易快速扫读。
- 截图支持点击放大预览，使用纯 HTML/CSS 锚点实现，不引入前端依赖。
- HTML 报告主时间线会隐藏成功的内部 `wait` 步骤和纯 `screenshot` 步骤；完整审计日志仍保留在 `report.json` 和任务 JSON 中。

## 已知问题

当前暂无明确阻塞 T007 CLI 黑盒 MVP 的已知问题。历史记录中的 LLM 检查、浏览器等待、截图采集、报告生成、失败恢复、选择器推荐和路径解析问题已在当前阶段处理。

仍需注意：

- `config/llm.env` 包含敏感信息，排查问题时不要输出或复制其中内容。
- `config/browser-states/*.json` 包含登录会话信息，排查问题时不要输出或复制其中内容。
- `argus browser check` 是浏览器能力调试入口；完整黑盒测试仍以 `argus run` 为准。
- LLM 调用失败时仍需区分代码问题、接口配置问题、代理 / TLS / 网络问题和模型服务问题。
- `config/prompts` 只作为用户覆盖目录；修改用户模板前注意和包内内置模板的差异。
- 修改前仍应先查看工作区状态，避免覆盖用户未提交改动。

## 待办清单

### 高优先级

- 为黑盒端到端闭环补充更多轻量单元测试，重点覆盖失败恢复、截图开关、报告路径回写和选择器解析。
- 梳理 T008 / 下一阶段范围，明确是否进入 Web API、任务列表页或更完整的项目管理能力。

### 中优先级

- 任务存储从临时 JSON 文件逐步演进到 SQLite + 文件系统。

### 低优先级

- 清理历史 `__pycache__`、临时文件和过时占位内容；清理前先确认不会影响用户本地运行产物。
- 后续如果进入 Web API 阶段，再补 FastAPI 项目结构、接口约定和数据模型边界。
- 后续如果进入 Java 白盒分析阶段，再补 `java_analyzer` 的 Maven 工程结构和 Python 调用边界。

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
examples/README.md
examples/task_001_screenshot.json
examples/task_002_multistep.json
argus_py/cli/main.py
argus_py/cli/messages.py
argus_py/core/paths.py
argus_py/core/constants.py
argus_py/config/settings.py
argus_py/config/llm_settings.py
argus_py/llm/client.py
argus_py/llm/models.py
argus_py/llm/prompts.py
argus_py/llm/prompts/llm_connection_check.md
argus_py/llm/prompts/blackbox_planner.md
argus_py/llm/prompts/blackbox_evaluator.md
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
argus_py/task/strategy.py
argus_py/report/html_report.py
argus_py/report/templates/base.html.j2
argus_py/report/templates/blackbox_report.html.j2
config/prompts/llm_connection_check.md
config/llm.env.example
```
