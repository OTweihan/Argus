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
# ── 权限策略 ──
# 1) .venv/bin/python3 是指向系统 Python（如 /usr/bin/python3）的符号链接。
#    chown -R 会跟随 symlink 污染系统文件，必须用 -h（no-dereference）。
# 2) uv run 在运行时可能往 /app 写入 .uv/ 元数据或同步 .venv，
#    因此 /app 和 .venv 整体必须归 pwuser 可写。
# 3) outputs / tmp/uv-cache 持久化目录直接 chown -R。
# 4) /app/config 可能含运行时生成的 fernet key，也归 pwuser。
RUN chown -Rh pwuser:pwuser /app/.venv \
 && find /app -mindepth 1 -maxdepth 1 ! -name .venv -exec chown -R pwuser:pwuser {} + \
 && chown pwuser:pwuser /app \
 && chown -R pwuser:pwuser /tmp/uv-cache
USER pwuser

EXPOSE 8000

# ── 健康检查 ──
# 直接使用 .venv 中的 Python，不绕 uv run（避免 uv 的 Python 解释器探测开销与权限问题）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD .venv/bin/python3 -c "import urllib.request,sys; \
urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5); sys.exit(0)" || exit 1

# ── 启动 ──
# 同样直接使用 .venv Python，跳过 uv run 的 Python 探测环节
CMD [".venv/bin/python3", "-m", "argus_py.cli.main", "serve", "--host", "0.0.0.0", "--port", "8000"]
