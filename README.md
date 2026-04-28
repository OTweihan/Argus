# Argus - AI Native Test Platform

> Every bug has nowhere to hide.

Argus 是一个面向 Web 应用质量保障场景的 AI Native 测试平台。当前阶段聚焦黑盒 MVP：用自然语言描述测试目标，由大模型规划浏览器动作，驱动 Playwright 执行，并输出结构化测试报告。

## 当前状态

当前处于第一阶段 CLI 本地模式，已完成 T001、T002、T003、T004、T005、T006 和 T007 的基础能力：

- T001 项目骨架：Python 包结构、CLI 入口、任务模型、报告模型、配置边界、占位模块。
- T002 浏览器封装：Playwright 生命周期、浏览器动作、截图、页面快照、轻量调试命令。
- T003 LLM 调用模块：OpenAI Chat Completions 兼容调用、Prompt 模板、响应模型、JSON 解析、重试逻辑、交互式配置命令。
- T004 任务模型与执行边界：任务 JSON 反序列化、文件存储读取、任务查询、状态流转、步骤日志、问题记录和可注册任务执行器。
- T005 黑盒 Agent 主逻辑：LLM 动作规划、浏览器动作执行、页面快照观察、LLM 结果评估、步骤日志和问题记录闭环。
- T006 报告生成：根据任务结果生成 HTML 和 JSON 报告，并回写任务报告路径。
- T007 CLI 端到端联调：`argus run` 已接入任务创建、黑盒执行、失败恢复、每步截图、报告输出和失败状态回写。

暂未完成：

- Web API、项目管理、数据库持久化、Java 白盒分析。

## 环境要求

- Windows 11
- PowerShell 7
- Python 3.11+
- Playwright 浏览器运行环境
- OpenAI Chat Completions 兼容的大模型 API

## 快速开始

在项目根目录执行：

```powershell
pip install -e ".[dev]"
argus --version
```

安装 Playwright Chromium：

```powershell
playwright install chromium
```

## 配置大模型

使用交互式命令配置：

```powershell
argus config llm
```

该命令会提示输入：

- API Key
- 接口地址
- 模型名称

API Key 输入时会显示星号掩码。配置会写入：

```text
config/llm.env
```

`config/llm.env` 不纳入版本控制，不要提交、复制或输出其中内容。

首次配置不会询问高级参数，默认使用内置值。需要调整最大输出 Token 数、温度、最大重试次数时执行：

```powershell
argus config llm --advanced
```

## 检查大模型连接

```powershell
argus llm check
```

该命令使用固定低消耗 Prompt 检查连接，不允许用户自由输入 Prompt，避免不必要的 token 消耗。

如果接口或代理响应较慢，可临时调大等待时间：

```powershell
argus llm check --timeout 90
```

临时覆盖模型或接口地址：

```powershell
argus llm check --model "qwen3.5-plus" --base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

## 检查浏览器能力

打开页面并截图：

```powershell
argus browser check --url "https://httpbin.org"
```

显示浏览器窗口：

```powershell
argus browser check --url "https://httpbin.org" --headed
```

指定截图路径：

```powershell
argus browser check --url "https://httpbin.org" --screenshot "outputs/screenshots/httpbin-check.png"
```

验证输入和点击：

```powershell
argus browser check --url "https://httpbin.org/forms/post" --fill-selector "input[name='custname']" --fill-text "WeiHan" --click "text=Submit"
```

浏览器封装会在系统层面等待页面稳定，常规情况下不需要手动增加等待。`--wait-ms` 仅作为额外调试参数。

## 执行黑盒任务

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org"
```

复杂流程可以直接用自然语言描述：

```powershell
argus run --goal "打开首页 → 点击链接 → 填写表单 → 提交 → 验证结果" --url "https://demo.playwright.dev/todomvc"
```

登录页或表单页建议把覆盖点写清楚：

```powershell
argus run --goal "全面测试登录界面，包括必填校验和错误登录提示" --url "https://example.com/login"
```

显示浏览器窗口执行：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org" --headed
```

只创建任务、不执行：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org" --create-only
```

执行完成后会输出任务状态、步骤数量、问题数量和 HTML 报告路径。报告默认写入：

```text
outputs/reports/<task_id>/index.html
outputs/reports/<task_id>/report.json
```

任务步骤、失败动作和最终结果会写入任务 JSON；默认每个执行步骤都会尽量保存截图，截图默认写入：

```text
outputs/screenshots/<task_id>/
```

不需要截图证据时可关闭：

```powershell
argus run --goal "打开页面并检查标题" --url "https://httpbin.org" --no-screenshot
```

关闭截图后，即使规划器输出 `screenshot` 动作，也只会记录“截图已按任务配置跳过”，不会保存图片。

`--max-steps` 和 `--timeout` 默认由系统根据任务描述自动分配；需要手动限制时仍可显式传入：

```powershell
argus run --goal "打开页面并截图" --url "https://httpbin.org" --max-steps 5 --timeout 180
```

当前自动分配策略：

| 任务类型 | 最大步数 | 超时 |
|----------|----------|------|
| 简单访问 / 截图 / 可访问性检查 | 6 | 180 秒 |
| 普通黑盒任务 | 12 | 300 秒 |
| 登录 / 表单 / 提交 / 流程类任务 | 20 | 600 秒 |

### 黑盒执行策略

- 初始动作由系统确定性打开起始 URL，后续动作由 LLM 基于页面快照和历史步骤规划。
- 每个成功或失败步骤都会尽量采集截图和页面快照，报告会展示步骤截图。
- 动作失败时不会立刻终止任务；系统会记录失败步骤、重新观察页面，并让规划器基于失败历史重新规划，默认最多恢复 2 次。
- 页面快照会给可交互元素生成推荐 selector，例如 `role=button[name="登录"]`、`css=[name="username"]`、`placeholder=请输入用户名`。
- 常见 LLM 误写的 `button:contains("登录")`、`a:contains("提交")` 会在选择器解析层自动转换为 Playwright 兼容定位。
- 对“测试登录界面”“测试表单”“测试页面功能”等目标，评估器不会仅因为元素存在就判定完成；需要看到实际输入、点击、提交、校验或错误提示等交互证据。

## 项目结构

```text
argus/
├── argus_py/
│   ├── cli/           # CLI 入口与交互提示文案
│   ├── api/           # 第二阶段 FastAPI 占位
│   ├── core/          # 常量、路径、枚举、异常、ID
│   ├── config/        # Python 配置加载模块
│   ├── llm/           # LLM 调用、Prompt、解析、重试
│   ├── task/          # 任务模型、状态、服务、文件存储边界
│   ├── blackbox/      # 黑盒 Agent 规划、评估、执行边界
│   ├── browser/       # Playwright 生命周期、动作、选择器、快照
│   ├── report/        # 报告模型、序列化、HTML/JSON 导出
│   ├── project/       # 第二阶段项目管理占位
│   ├── infra/         # 第二/三阶段基础设施占位
│   ├── whitebox/      # 第三阶段 Java 白盒分析客户端占位
│   └── utils/         # 通用工具
├── config/
│   ├── prompts/       # Prompt 模板
│   ├── llm.env        # 本地大模型配置，不提交
│   ├── llm.env.example
│   └── logging.yaml
├── docs/
│   └── project-info/  # 项目上下文、变更、问题、待办
├── outputs/           # 运行产物，内容不纳入版本控制
├── tests/             # 单元测试骨架
├── examples/          # 示例任务 JSON
├── scripts/           # 开发脚本占位
└── java_analyzer/     # 第三阶段 Java 白盒分析子模块占位
```

## 路径策略

项目通过 `argus_py/core/paths.py` 统一解析路径：

- 默认从项目根目录读取 `config/llm.env`、`config/prompts`、报告模板和 `outputs`。
- 从其他目录执行 `argus` 时，不会因为当前工作目录变化导致配置或模板找不到。
- 可通过环境变量 `ARGUS_PROJECT_ROOT` 覆盖项目根目录。

顶层 `config/` 目录只放配置数据，不放 Python 模块，避免和 `argus_py.config` 混淆。

## 项目上下文

后续维护前先阅读：

```text
docs/project-info/PROJECT_CONTEXT.md
```

该文档记录了当前阶段、近期改动、已知问题、待办事项和重点文件索引。

## 技术栈

| 组件 | 选型 |
|------|------|
| Python | 3.11+ |
| LLM | OpenAI Chat Completions 兼容接口 |
| 默认模型 | 百炼 Qwen3.5-Plus |
| 浏览器自动化 | Playwright Python |
| 报告 | Jinja2 HTML + JSON |
| MVP 存储 | JSON 文件 + 文件系统 |
| 后续存储 | SQLite + 文件系统 |
| Java 子模块 | Java 17 + Maven（第三阶段） |

## 注意事项

- 不要提交 `config/llm.env`。
- 不要在日志、文档或提交信息中输出 API Key。
- `argus browser check` 是浏览器封装调试入口，完整测试执行使用 `argus run`。
- 当前 LLM 检查命令只验证连接，不用于自由 Prompt 调试。
- 工作区可能存在大量未提交变更，修改前先查看 `git status --short`。
