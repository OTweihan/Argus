# syntax=docker/dockerfile:1.7

# ============================================================================
# Frontend build stage
# Vue 3 + Element Plus 静态产物输出到 argus_py/api/static，runtime stage 复制
# ============================================================================
FROM node:20-bookworm-slim AS frontend
WORKDIR /workspace

# 先复制依赖描述，让 lockfile 命中 docker layer 缓存
COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN corepack enable \
 && corepack prepare pnpm@9 --activate \
 && cd frontend \
 && pnpm install --frozen-lockfile

# 复制前端源码并构建（vite.config.ts 已配 outDir=../argus_py/api/static）
COPY frontend ./frontend
RUN mkdir -p ./argus_py/api/static \
 && cd frontend \
 && pnpm build

# ============================================================================
# Runtime stage
# Playwright 官方镜像预装 chromium + 所有系统依赖（libnss、字体、xvfb 等）
# 选 v1.58.0-jammy：与 uv.lock 锁定的 playwright==1.58.0 对齐
# 若需要更新 Playwright 版本，请同步 pyproject.toml 的 playwright>= 约束
# ============================================================================
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

# stdout 不缓冲；防止 docker logs 看不到实时输出
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache

WORKDIR /app

# 装 uv：lock-aware、并发安装、Python 自动管理
# 固定 0.4.x 兼容当前 uv.lock 格式；升级时需要重新生成锁
RUN pip install --no-cache-dir "uv>=0.4,<1.0"

# ── 安装依赖（以 pwuser 身份创建 .venv，避免运行时符号链接权限问题）──
# 策略说明：
#   uv run 在运行时需要 canonicalize .venv/bin/python3（指向系统 Python 的
#   符号链接）。如果 .venv 由 root 创建再 chown，符号链接本身虽可改属主，
#   但 uv 的实际文件操作（stat/open）仍会在某些内核版本 / overlay 配置下
#   触发 EACCES。让 pwuser 自始至终拥有 .venv 是最可靠的方案。
RUN mkdir -p /tmp/uv-cache && chown -R pwuser:pwuser /tmp/uv-cache
RUN chown pwuser:pwuser /app

# 先切 pwuser → 安装依赖（创建 .venv），再切回 root 复制源码
USER pwuser
COPY pyproject.toml uv.lock README.md /app/
RUN uv sync --frozen --no-install-project

USER root
# 复制源码 + 配置 + 前端构建产物
COPY argus_py /app/argus_py
COPY config /app/config
COPY --from=frontend /workspace/argus_py/api/static /app/argus_py/api/static

# 持久化挂载点：DB、截图、trace、日志全部在此
RUN mkdir -p /app/outputs/data \
             /app/outputs/screenshots \
             /app/outputs/logs \
             /app/outputs/reports \
             /app/outputs/traces \
             /app/outputs/temp \
             /app/outputs/backups \
 && chown -R pwuser:pwuser /app/outputs

# 安装项目自身到 .venv（pwuser 已有的 .venv 中注册项目包）
USER pwuser
RUN uv sync --frozen

EXPOSE 8000

# ── 健康检查 ──
# 直接使用 .venv 中的 Python，不绕 uv run
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD .venv/bin/python3 -c "import urllib.request,sys; \
urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5); sys.exit(0)" || exit 1

# ── 启动 ──
# 同样直接使用 .venv Python，跳过 uv run 的 Python 探测环节
CMD [".venv/bin/python3", "-m", "argus_py.cli.main", "serve", "--host", "0.0.0.0", "--port", "8000"]
