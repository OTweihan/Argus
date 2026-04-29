# 示例任务

本目录保存当前任务模型的 JSON 示例，字段名与 `argus_py.task.models.Task` 保持一致。

## 文件说明

- `task_001_screenshot.json`：简单访问和截图任务，对应 CLI 自动分配的简单任务限制。
- `task_002_multistep.json`：表单 / 提交流程任务，对应 CLI 自动分配的复杂任务限制。

## CLI 对照

当前 CLI 不直接读取这些 JSON 文件。执行同类任务时使用：

```powershell
argus run --goal "打开 https://httpbin.org 并截图" --url "https://httpbin.org"
```

```powershell
argus run --goal "打开 httpbin 表单页，填写客户姓名，提交表单并记录结果" --url "https://httpbin.org/forms/post"
```

只创建任务快照、不执行黑盒闭环时使用：

```powershell
argus run --goal "打开 https://httpbin.org 并截图" --url "https://httpbin.org" --create-only
```

## 字段说明

- `goal`：自然语言测试目标。
- `start_url`：黑盒任务起始 URL。
- `task_type`：当前阶段使用 `blackbox`。
- `status`：示例任务初始状态为 `pending`。
- `max_steps`：最大执行步骤数。
- `timeout_seconds`：任务超时时间，单位秒。
- `capture_screenshots`：是否采集步骤截图。
- `parameters`：预留扩展参数，当前 CLI 主要通过命令行参数传入浏览器类型和 headed 模式。
