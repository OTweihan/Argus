# Argus Phase2 端到端测试用例

## 范围

覆盖 T009-T016 的平台化主链路：FastAPI、项目管理、任务管理、异步调度、WebSocket 实时事件、模型配置、Web 控制台和 CLI/Web 并存。

## 前置条件

- Python 3.11+
- 已安装项目依赖
- 已安装 Playwright Chromium
- 如执行真实黑盒任务，需要可用的 LLM 配置或平台模型配置
- 如验证 Web 控制台，需要先构建前端静态产物

```powershell
cd D:\PythonProjects\Argus\frontend
npm install
npm run build
cd D:\PythonProjects\Argus
argus serve --host 127.0.0.1 --port 8000
```

## 自动化契约测试

| ID | 用例 | 命令 | 预期 |
|----|------|------|------|
| E2E-AUTO-001 | 平台核心链路契约 | `pytest tests/e2e/test_platform_contract.py` | 项目创建、任务创建、入队、后台执行、事件发布、报告回写全部通过 |
| E2E-AUTO-002 | 持久化契约 | `pytest tests/e2e/test_platform_contract.py` | 重建服务对象后项目和任务仍可读取 |
| E2E-AUTO-003 | CLI/Web 命令并存 | `pytest tests/e2e/test_platform_contract.py` | `argus serve` 与 `argus run` 参数解析互不冲突 |

验证记录：

- 2026-05-02：用户执行 `pytest tests/e2e/test_platform_contract.py`，结果 `3 passed`。
- 首次执行出现 FastAPI `on_event` deprecation warning，已将应用生命周期改为 `lifespan` 写法；该警告修复未再次复测。

## 手工验收用例

### E2E-MANUAL-001 Web 控制台打开

步骤：

1. 构建前端。
2. 启动 `argus serve --host 127.0.0.1 --port 8000`。
3. 浏览器访问 `http://127.0.0.1:8000/`。

预期：

- 能打开 Argus 控制台。
- 仪表盘、项目、任务、模型四个视图可切换。
- `/docs` 仍可打开 OpenAPI 文档。

### E2E-MANUAL-002 项目创建

步骤：

1. 打开“项目”视图。
2. 创建项目：
   - 名称：`E2E Demo`
   - 基础 URL：`https://demo.playwright.dev/todomvc`
   - 默认最大步骤：`6`
   - 默认超时秒数：`180`
3. 保存。

预期：

- 项目列表出现新项目。
- 刷新页面后项目仍存在。

### E2E-MANUAL-003 模型配置

步骤：

1. 打开“模型”视图。
2. 新增一个模型配置。
3. 点击“测试”。

预期：

- 保存后列表出现模型配置。
- 响应中不展示 API Key 明文，只展示 Key 是否已配置。
- 连接检查成功时显示耗时；失败时显示统一错误信息。

### E2E-MANUAL-004 创建并启动任务

步骤：

1. 打开“任务”视图。
2. 选择 `E2E Demo` 项目。
3. 目标填写：`打开 TodoMVC 页面，添加一个待办项，然后确认页面出现该待办项`。
4. 选择模型配置。
5. 创建任务。
6. 点击启动。

预期：

- 任务初始状态为 `pending`。
- 启动后进入后台队列。
- 执行中状态变为 `running`。
- 任务完成后进入 `completed`、`failed` 或 `timeout` 终态。

### E2E-MANUAL-005 实时日志

步骤：

1. 在任务详情中保持页面打开。
2. 启动任务。
3. 观察步骤日志区域。

预期：

- WebSocket 状态显示已连接。
- 任务状态、步骤日志、问题和完成事件能实时刷新。
- 空闲时不会断开；服务端会发送 keepalive。

### E2E-MANUAL-006 报告下载

步骤：

1. 任务进入终态后，点击 HTML 报告。
2. 点击 JSON 报告。

预期：

- HTML 报告可打开。
- JSON 报告可读取。
- 报告包含任务基本信息、步骤、问题和结果摘要。

### E2E-MANUAL-007 多任务并发

步骤：

1. 修改 `config/server.yaml`：
   - `scheduler.concurrency: 3`
2. 启动 Web 服务。
3. 连续创建并启动 3 个任务。

预期：

- 3 个任务互不覆盖日志、状态和报告。
- 同一个任务不能重复入队。
- 每个任务详情只展示自己的事件。

### E2E-MANUAL-008 服务重启后数据不丢失

步骤：

1. 创建项目和任务，但不删除。
2. 停止 Web 服务。
3. 重新启动 Web 服务。
4. 打开控制台或调用 API 查询项目和任务。

预期：

- SQLite 中的项目仍存在。
- 文件系统中的任务快照仍存在。
- 已完成任务的报告路径仍可查询。
- 进程内队列和进程内 WebSocket 历史不会恢复，这是当前设计限制。

### E2E-MANUAL-009 CLI/Web 并存

步骤：

1. 执行 `argus run --goal "打开页面" --url "https://example.com" --create-only`。
2. 执行 `argus serve --host 127.0.0.1 --port 8000`。

预期：

- CLI 创建任务功能可用。
- Web 服务可启动。
- 两种入口使用同一套代码模型，不互相破坏配置。

## 当前限制

- `pause` 仍返回 501。
- running 状态任务暂不支持可靠 stop。
- 进程内队列不会在服务重启后恢复。
- 进程内 WebSocket 历史不会在服务重启后恢复。
- T015 前端需要先执行 `npm install` 和 `npm run build` 才会由 FastAPI 托管。
