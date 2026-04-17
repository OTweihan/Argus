# Argus - AI Native Test Platform

> Every bug has nowhere to hide.

## 概述

Argus 是一个 AI Native 测试平台，通过自然语言驱动浏览器操作，自动探索测试、发现问题、输出结构化报告。

## 阶段

当前阶段：**第一阶段（黑盒 MVP）** - CLI 模式，跑通"自然语言 -> AI 操作浏览器 -> 输出报告"的闭环。

## 快速开始

### 1. 安装依赖

```bash
pip install -e ".[dev]"
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 LLM API Key
```

### 3. 安装 Playwright 浏览器

```bash
playwright install chromium
```

### 4. 运行

```bash
# 查看版本
argus --version

# 运行测试任务
argus run --goal "打开页面并截图" --url "https://httpbin.org"
```

## 项目结构

```
argus/
├── argus_py/          # Python 主系统
│   ├── cli/           # CLI 入口
│   ├── core/          # 常量、枚举、异常
│   ├── llm/           # LLM 调用
│   ├── task/          # 任务模型与执行
│   ├── blackbox/      # 黑盒 Agent
│   ├── browser/       # Playwright 封装
│   ├── report/        # 报告生成
│   └── utils/         # 工具函数
├── config/            # 配置文件 + Prompt 模板
├── outputs/           # 运行产物
├── tests/             # 测试
├── examples/          # 示例任务
└── scripts/           # 开发脚本
```

## 技术栈

| 组件 | 选型 |
|------|------|
| Python | 3.11+ |
| LLM | 百炼 Qwen3.5-Plus |
| 浏览器自动化 | Playwright |
| 报告 | Jinja2 (HTML) + JSON |
| 存储 | SQLite + 文件系统 |

## 许可证

MIT
