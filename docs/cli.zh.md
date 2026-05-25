# Argus 命令行参考

[English](cli.md)

## 概述

Argus 提供单个 `argus` CLI 命令，包含多个子命令。所有命令共享全局选项。

### 全局选项

| 选项 | 说明 |
|--------|------|
| `--version` | 显示版本 |
| `-v` | 详细输出（INFO 级别） |
| `-vv` | 非常详细输出（DEBUG 级别） |
| `--help` | 显示帮助 |

---

## `argus run` — 执行黑盒测试任务

核心命令。用自然语言描述测试目标，Argus 负责规划、执行和报告生成。

```bash
argus run --goal "打开页面并截图" --url "https://httpbin.org"
```

### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--goal` / `-g` | 是 | 自然语言描述的测试目标 |
| `--url` / `-u` | 是 | 测试目标 URL |
| `--headed` | 否 | 执行时显示浏览器窗口（默认无头模式） |
| `--auth-state` | 否 | 复用已保存的浏览器登录态（名称或 JSON 文件路径） |
| `--no-screenshot` | 否 | 关闭步骤截图 |
| `--create-only` | 否 | 仅创建任务快照，不执行 |
| `--project` | 否 | 关联项目 ID |
| `--max-steps` | 否 | 覆盖最大规划步数 |
| `--timeout` | 否 | 覆盖执行超时（秒） |
| `--planner-extension` | 否 | Planner Prompt 扩展规则 Markdown 文件路径 |
| `--evaluator-extension` | 否 | Evaluator Prompt 扩展规则 Markdown 文件路径 |

### 执行策略

未指定 `--max-steps` 和 `--timeout` 时，系统根据目标自动推断限制：

| 任务类型 | 最大步数 | 超时 |
|----------|---------|------|
| 简单访问/截图/可访问性检查 | 6 | 180 秒 |
| 普通黑盒任务 | 12 | 300 秒 |
| 登录/表单/提交/流程类任务 | 20 | 600 秒 |

### 失败恢复

动作失败不会中止任务。系统会记录失败、重新观察页面，并让规划器基于失败历史重新规划（默认最多恢复 2 次）。恢复尝试全部用尽后，任务以失败状态结束，但仍会生成报告。

### 示例

```bash
# 基础截图
argus run --goal "打开页面并截图" --url "https://httpbin.org"

# 多步骤流程
argus run --goal "打开首页 → 点击链接 → 填写表单 → 提交 → 验证结果" \
  --url "https://demo.playwright.dev/todomvc"

# 登录页验证
argus run --goal "测试登录界面——检查必填校验、错误提示和登录失败消息" \
  --url "https://example.com/login"

# 显示浏览器窗口
argus run --goal "打开页面并截图" --url "https://httpbin.org" --headed

# 复用登录态
argus run --auth-state example.com \
  --goal "检查个人中心页面是否正常展示" \
  --url "https://example.com/profile"

# 仅创建任务快照
argus run --goal "打开页面并截图" --url "https://httpbin.org" --create-only

# 关闭截图
argus run --goal "检查页面标题" --url "https://httpbin.org" --no-screenshot

# 手动限制
argus run --goal "复杂表单流程" --url "https://example.com/form" --max-steps 5 --timeout 180
```

### 输出

执行完成后会显示任务状态、步骤数量、问题数量和报告路径：

- **报告：** `outputs/reports/<task_id>/index.html` 和 `outputs/reports/<task_id>/report.json`
- **截图：** `outputs/screenshots/<task_id>/`（每个执行步骤一张）

---

## `argus serve` — 启动 Web 服务器

启动 FastAPI Web 服务器，包含 Web 控制台和 REST API。

```bash
argus serve
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 绑定地址 |
| `--port` | `8000` | 端口 |
| `--reload` | 禁用 | 启用开发热重载 |

### 启动后访问

- **Web 控制台：** `http://localhost:8000/` — Vue 3 SPA，管理项目、任务和模型
- **REST API：** `http://localhost:8000/argus/api/` — 完整 RESTful API
- **OpenAPI 文档：** `http://localhost:8000/docs` — 交互式 Swagger UI
- **WebSocket：** `ws://localhost:8000/argus/api/ws/tasks/{id}` — 实时任务事件

---

## `argus browser check` — 调试浏览器能力

验证 Playwright 浏览器集成，调试选择器，可选页面交互。

```bash
argus browser check --url "https://httpbin.org"
```

### 参数

| 参数 | 说明 |
|------|------|
| `--url` | 要打开的 URL |
| `--headed` | 显示浏览器窗口 |
| `--screenshot` | 自定义截图保存路径 |
| `--fill-selector` | 要填写的 CSS 选择器 |
| `--fill-text` | 要输入的文字 |
| `--click` | 要点击的选择器 |
| `--wait-ms` | 截图前额外等待时间（毫秒） |

### 示例

```bash
# 基础检查
argus browser check --url "https://httpbin.org"

# 显示浏览器窗口
argus browser check --url "https://httpbin.org" --headed

# 自定义截图路径
argus browser check --url "https://httpbin.org" --screenshot "outputs/screenshots/debug.png"

# 填写表单并点击
argus browser check --url "https://httpbin.org/forms/post" \
  --fill-selector "input[name='custname']" --fill-text "WeiHan" \
  --click "text=Submit"
```

浏览器封装会自动等待页面稳定，`--wait-ms` 仅作为额外调试参数。

---

## `argus auth` — 浏览器登录态管理

保存和复用浏览器认证状态（cookies、localStorage）。

### `argus auth save`

打开浏览器窗口手动登录，然后保存会话状态。

```bash
argus auth save --url "https://example.com/login"
```

| 参数 | 说明 |
|------|------|
| `--url` | 登录页面 URL |
| `--name` | 自定义状态名称（默认从主机名自动派生） |

命令默认显示浏览器窗口。完成登录后回到终端按 Enter，状态保存到 `config/browser-states/<name>.json`。

```bash
# 自定义名称
argus auth save --name example-admin --url "https://example.com/login"
```

端口处理：如果 URL 包含端口，名称中的 `:` 会被替换为 `-`（例如 `http://10.18.90.80:8580/login` 保存为 `config/browser-states/10.18.90.80-8580.json`）。

### `argus auth list`

列出所有已保存的登录态。

```bash
argus auth list
```

显示登录态名称、关联站点、修改时间、复用命令和文件路径。

### 复用登录态

在执行任务时传入 `--auth-state`：

```bash
argus run --auth-state example.com --goal "检查个人中心页面" --url "https://example.com/profile"
```

`--auth-state` 接受登录态名称或 JSON 文件路径。

> 登录态文件包含 Cookie、LocalStorage 等会话信息，已通过 `.gitignore` 排除。请按敏感文件处理，不要提交或外发。

---

## `argus llm check` — 验证 LLM 连通性

使用固定低消耗 Prompt 测试大模型 API 连接（不允许用户输入，避免不必要的 token 消耗）。

```bash
argus llm check
```

### 参数

| 参数 | 说明 |
|------|------|
| `--timeout` | 覆盖等待时间（默认 60 秒） |
| `--model` | 临时覆盖模型名称 |
| `--base-url` | 临时覆盖 API 地址 |

### 示例

```bash
# 默认检查
argus llm check

# 慢接口调大超时
argus llm check --timeout 90

# 临时覆盖模型和地址
argus llm check --model "qwen3.5-plus" --base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

---

## `argus config llm` — 配置大模型

交互式配置大模型 API 连接。

```bash
argus config llm
```

提示输入：
- API Key（输入时显示星号掩码）
- 接口地址
- 模型名称

配置保存在数据库（API Key 加密存储）。

### 高级配置

```bash
argus config llm --advanced
```

额外提示输入：
- 最大输出 Token 数
- 温度
- 最大重试次数

首次使用按内置默认值配置。只在需要调整时使用 `--advanced`。

---

## `argus --version`

```bash
argus --version
```

显示当前版本号。
