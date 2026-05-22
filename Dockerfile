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

# 复制依赖描述，先 sync 命中 layer 缓存
COPY pyproject.toml uv.lock README.md /app/
RUN uv sync --frozen --no-install-project

# 复制源码 + 配置 + 前端构建产物
COPY argus_py /app/argus_py
COPY config /app/config
COPY --from=frontend /workspace/argus_py/api/static /app/argus_py/api/static

# 安装项目自身（链接到现有 .venv）
RUN uv sync --frozen

# 持久化挂载点：DB、截图、trace、日志全部在此
RUN mkdir -p /app/outputs/data \
             /app/outputs/screenshots \
             /app/outputs/logs \
             /app/outputs/reports \
             /app/outputs/traces \
             /app/outputs/temp \
             /app/outputs/backups

# 切换到 non-root 用户（playwright 镜像内置 pwuser:1000）
# config 与 outputs 都需要写权限：fernet key 自动生成、DB 写入
# uv cache 目录在 build 阶段由 root 创建，运行时 pwuser 必须可写
RUN chown -R pwuser:pwuser /app /tmp/uv-cache
USER pwuser

EXPOSE 8000

# /health 由 argus_py.api.routes.health 提供；只用 stdlib，无需装 curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import urllib.request,sys; \
urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); sys.exit(0)" || exit 1

# CLI 启动会跑 _detect_multi_worker_env 护栏，挡住 K8s 误调 WEB_CONCURRENCY > 1
CMD ["uv", "run", "argus", "serve", "--host", "0.0.0.0", "--port", "8000"]
