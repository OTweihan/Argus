# Argus 私网部署指南

[English](deployment.md)

本文档面向公司内部 / 私网部署场景。覆盖容器化、配置基线、SSRF / Origin / Fernet key 等安全防御、备份与升级、多副本约束。

> 浏览自动化用 Playwright，必须用官方 Playwright Python 镜像（已预装 Chromium + libnss / 字体 / xvfb），不要自己拼 base 镜像。

---

## 1. 部署架构

```
                      ┌─────────────────┐
            (HTTPS)   │  Reverse Proxy  │   公司 SSO / 网关（可选）
    Browser ──────────► │  Nginx / Caddy  │
                      └────────┬────────┘
                               │ (HTTP, internal)
                      ┌────────▼────────┐
                      │  Argus container│   单副本（硬约束，见 §6）
                      │  uv + uvicorn   │
                      └────────┬────────┘
                               │ volume
                  ┌────────────┴────────────┐
                  │  outputs/data/argus.db  │  WAL 模式 SQLite
                  │  outputs/screenshots/   │
                  │  outputs/traces/        │
                  │  outputs/backups/       │
                  └─────────────────────────┘
```

---

## 2. 快速启动（Docker Compose）

```bash
# 首次构建并启动
docker compose up -d --build

# 含 Java 源码分析（附加 java-analyzer）
docker compose --profile java up -d --build

# 查看运行状态
docker compose ps
docker compose logs -f argus

# 升级
git pull
docker compose build
docker compose up -d
```

启动后访问 `http://<host>:8000/` 打开 Console，`/docs` 是 OpenAPI / Swagger。

### 默认网络边界（fail-closed）

仓库自带的 `docker-compose.yml` 默认是**收紧**的：

- **Python** 宿主端口只绑定 `127.0.0.1`（`127.0.0.1:8000:8000`），不会暴露到局域网；
  容器内 uvicorn 仍监听 `0.0.0.0`，由 compose 的回环绑定收敛宿主侧可见性。
- **Java Analyzer** 只 `expose` 给 Compose 内部网络（Python 通过
  `http://java-analyzer:8081` 访问），**不映射宿主端口**。Java Analyzer 不是
  可信公网接口，只应被 Python 控制面调用。
- 容器内强制 `allowed-source-roots=/tmp/sources`（Python 与 Java 双侧），
  非共享目录的源码路径会被 Java 拒绝（real-path 校验 + 符号链接逃逸拒绝）。

**确需把 Console 暴露到内网其他机器**时，复制 `docker-compose.intranet.example.yml`
并设置强随机 `ARGUS_API_TOKEN`：

```bash
cp docker-compose.intranet.example.yml docker-compose.intranet.yml
# 编辑 docker-compose.intranet.yml：设置 ARGUS_API_TOKEN（openssl rand -hex 32）
docker compose --profile java -f docker-compose.yml -f docker-compose.intranet.yml up -d
```

覆盖文件会清空基线 compose 的 `ARGUS_BIND_LOOPBACK_ONLY` 标记；因此若
Token 仍是占位符/为空，`argus serve` 启动时会打印显式告警（非回环监听 + 无 Token）。
`docker-compose.intranet.yml` 已加入 `.gitignore`，防止把真实 Token 提交进仓库。

---

## 3. 配置基线（`config/server.yaml`）

> 修改后无需重建镜像；compose 通过 bind mount 实时生效，重启容器即可。

### CORS

```yaml
cors:
  allow_origins:
    - https://argus.internal.example.com   # 反代域名
    - http://localhost:8000                # 本地直连
```

`allow_origins` 同时决定 **WebSocket Origin 白名单**：浏览器从其他内网页面发起跨域 WS 不会被接受（私网钓鱼防御）。CLI / 服务器到服务器（无 Origin）放行。

### LLM SSRF 防御

```yaml
llm:
  # 默认拒绝 RFC1918 私网 / cloud metadata；放行 localhost、127.0.0.1
  # 把内网自部署 LLM 主机加入白名单
  allow_private_hosts:
    - 10.10.20.5
    - llm.internal.example.com
```

未列入的内网地址在 `/config/models/test` 与持久化创建 / 更新模型配置时都会被拒绝，错误码 `MODEL_CONFIG_ERROR`。

### 白盒源码快照

Python 会先将 Git 或本地源码物化为任务独立快照，Java Analyzer 只分析该快照。
两个容器必须以同一绝对路径挂载同一个 volume。仓库自带的
`docker-compose.yml` 已将 `java-analyzer-sources` 同时挂载到两个服务的 `/tmp/sources`，
并为 Python 设置：

```text
ARGUS_WHITEBOX_SOURCE_WORK_DIR=/tmp/sources
ARGUS_WHITEBOX_ALLOWED_SOURCE_ROOTS=/tmp/sources
ARGUS_JAVA_ANALYZER_URL=http://java-analyzer:8081
```

Java 侧通过 `argus.analysis.allowed-source-roots` 做 real-path 边界校验（越界与
符号链接逃逸一律拒绝）；容器由 Dockerfile/Compose 固定为 `/tmp/sources`。

非容器部署可在 `config/server.yaml` 中配置：

```yaml
whitebox:
  source_work_dir: /path/visible/to/python-and-java
  allowed_source_roots:
    - /srv/projects
```

> **allowed-source-roots 过渡期**：未配置时 Python（`serve`）与 Java（`SourceLocator`）
> 都会打印宽松模式告警——允许 Java 进程可见的任意目录，保持旧行为兼容；容器/生产
> 部署必须显式配置并最终 fail-closed。对应环境变量：
> `ARGUS_WHITEBOX_ALLOWED_SOURCE_ROOTS`（Python，逗号分隔）、
> `ARGUS_ANALYSIS_ALLOWED_SOURCE_ROOTS`（Java，逗号分隔）。

快照在远端作业确认结束后按任务清理。Python 取消、超时或断网时无法确认 Java
是否仍在读取，因此保留快照，由 24 小时 TTL 清理回收。

> **手动清理源码卷**：TTL 只由 Python 容器维护。若 Python 容器停止超过 24
> 小时，`java-analyzer-sources` 卷持续增长。可用以下命令手动清理：
> `docker compose down -v`（会同时删除 outputs 卷），或删除
> `argus-java-analyzer-sources` 卷后重启：`docker volume rm argus-java-analyzer-sources`
> 再 `docker compose --profile java up -d`。

### Body 大小限制

```yaml
request:
  max_body_size_bytes: 5242880   # 默认 5 MB，对正常 prompt / 表单足够
```

### 调度并发

```yaml
scheduler:
  concurrency: 4                 # 单进程内的并发任务数；不是副本数
```

### WebSocket 并发上限

```yaml
events:
  max_subscribers: 0   # 0 = 不限（向后兼容），建议设为 5× 预期并发用户数
```

每个 WS 订阅独占一个 `asyncio.Queue`（容量 = `subscriber_queue_size`），异常前端反复重连可能耗尽内存。命中上限后新订阅会被 `EventBusSubscriberLimitError` 拒绝，前端会收到 WebSocket close code **1013（service overload）**而非 1008，方便客户端实现指数退避重试。

### 限流（可选）

```yaml
rate_limit:
  enabled: true
  trust_forwarded: true            # 反代后部署时打开（取 X-Forwarded-For）
  routes:
    - name: create_task
      method: POST
      path: /tasks
      requests_per_minute: 60
      burst: 20
    - name: start_task
      method: POST
      path: /tasks/*/start
      requests_per_minute: 60
      burst: 20
```

实现是进程内 token bucket，按 `(client_ip, rule.name)` 分桶。命中限流后返回 **HTTP 429** + `Retry-After`，前端会收到 `error.code = "RATE_LIMITED"`。

> 单 worker 假设下进程内状态足够。多副本部署前需要切到 Redis / 共享存储。

### 可选 API Token 鉴权

适用场景：私网内 Argus 没有放在 SSO 反代后面、又想给 API 加一层口令。设置环境变量即可启用：

```bash
ARGUS_API_TOKEN=请生成一个32字节以上的随机串
```

启用后：

| 路径前缀 | 是否需要 token |
|---------|---------------|
| `/health` | 否（反代/容器健康检查匿名探测） |
| `/`、`/assets/...` SPA 静态 | 否（浏览器加载 HTML 无法带 header） |
| `/argus/api/*` | **是**（`Authorization: Bearer <token>`） |
| `/argus/api/ws/*` | **是**（浏览器走短时单次 `?token=<ticket>`，CLI 可走 Bearer 头） |

**WebSocket 不携带长期 Token**：浏览器先 `POST /argus/api/ws/token`（Bearer 头）
换取一个 HMAC 签名的**短时（默认 30 秒）、单次** ticket，再带 `?token=<ticket>`
建立 WebSocket。长期 Token 因此不会出现在 WS URL 中，也就不会进入反代访问日志
或接入侧日志。旧版前端/CLI 直接带长期 Token 仍兼容（保留一个版本窗口）。

Web 控制台第一次收到 401 时会显示 Token 输入框，Token 只保存在当前标签页的
`sessionStorage`；关闭标签页即清除。截图、报告和调试包均通过带 Bearer 头的请求加载，
不会把 Token 放进普通 HTTP URL 或前端构建产物。校验使用 `hmac.compare_digest`
防时序侧信道。**不要把 token 写进 git**。更强的访问控制请走反代 + SSO。

### 就绪探针

`/ready` 在依赖未就绪或 lifespan 尚未完成初始化时返回 **HTTP 503**（而非 200），
供 K8s / Compose / 反代按状态码停止导流；`/health` 只表示进程存活，不做昂贵
依赖检查。依赖恢复后 `/ready` 回到 200。

就绪判定读取 **lifespan 成功初始化的容器状态**（`app.state.container`），而不是
通过依赖 getter 现场组装：

| 依赖 | 就绪条件 |
|------|---------|
| DB | SQLite 连通（带 5s TTL 缓存，避免高频探针竞争锁） |
| Worker | `health_snapshot()`：已启动 **且** 存活 loop 数 > 0。loop 全部异常退出（`crashed_loops` 累积、`alive_loops` 归零）时返回 503 |
| EventBus | 已初始化 **且** 当前有事件循环可派发（无 loop 时 publish 只写 history、无法推送 WebSocket，判未就绪） |

`/metrics` 额外暴露 `worker_total_loops` / `worker_alive_loops` /
`worker_crashed_loops` / `worker_last_consume_stale_seconds`，供监控区分
"Worker 在跑"与"Worker 已异常退出但进程未死"。

> 依赖 `/ready` 的脚本请以 HTTP 状态码为准；503 表示未就绪/需停流，200 才可导流。

---

## 4. 敏感文件

| 路径 | 用途 | 备份 | 权限 |
|------|------|------|------|
| `config/.fernet_key` | model_configs 的 API Key 加解密 | **必须** | POSIX `chmod 600`（Argus 启动时自动收紧） |
| `outputs/data/argus.db` | SQLite 全量数据（含模型配置） | 每日 | 600 |
| `outputs/data/argus.db-wal` | WAL 日志 | 由 backup 工具一并 copy | 600 |

> Argus 启动时会检查 `config/.fernet_key` 文件权限：POSIX 下若 group/other 可读，会打 WARN 日志提示 `chmod 600`。Linux 多人 SSH 服务器尤其需要注意。

---

## 5. 备份与恢复

### 日常备份（推荐每日）

```bash
# 容器内执行，--keep 7 自动只保留 7 份
docker compose exec argus python scripts/backup_db.py --keep 7

# 或 host 上挂载相同 volume 后执行
python scripts/backup_db.py --keep 7
```

备份产物结构：

```
outputs/backups/20260519T161003Z/
├── argus.db        # 在线热备（事务一致）
└── .fernet_key     # 同时备份解密密钥
```

### 灾难恢复

1. 停服：`docker compose down`
2. 把目标时间戳目录的 `argus.db` 与 `.fernet_key` 还原到原位（容器内 `/app/outputs/data/` 与 `/app/config/`）
3. 启服：`docker compose up -d`

### 过期产物清理

```bash
docker compose exec argus python scripts/cleanup_outputs.py --days 30
```

默认清 `screenshots / logs / temp / reports / traces` 30 天前文件；`data / backups` 是受保护目录，本脚本拒绝清。

---

## 6. 多副本约束（重要）

Argus 当前使用 **进程内 asyncio.Queue + 进程内 EventBus**，多 worker / 多副本会导致：

- 同一任务被两个进程同时消费（任务双发）
- WebSocket 事件只能广播到当前进程的订阅者（前端事件丢失 N-1/N）
- `lru_cache` 单例分裂，依赖注入状态不一致

防御措施：

1. `argus serve` 启动时检测 `WEB_CONCURRENCY` / `UVICORN_WORKERS` env，若 > 1 直接拒启
2. lifespan 兜底拒启：绕过 CLI 用 `uvicorn ... --workers N` 时抛 `RuntimeError`（不是告警）
3. **outputs 目录跨进程独占锁**（OS 文件锁，进程退出自动释放）：两个进程指向同一
   DB/outputs 时，后启动者拿不到锁，直接拒绝启动——这是无法识别启动方式时的最终防线
4. `docker-compose.yml` 显式 `deploy.replicas: 1` 与 env `WEB_CONCURRENCY=1`
5. K8s Deployment 必须 `replicas: 1`，HPA 关闭

> 锁文件为 `outputs/.argus-singleton.lock`（持锁者信息写入同名 `.owner` sidecar）。
> 若残留该文件但进程已退出，无需手动删除——OS 锁已随进程释放，下次启动会自动重写。

> 如未来需要横向扩展，第一步是把 queue / EventBus 切外置（Redis Streams、NATS 等），再放开副本数。

---

## 7. Schema 升级

`argus_py/infra/migrations/` 是版本化 schema 迁移目录，启动期 `apply_migrations()` 自动按 `0001_xxx.sql`、`0002_xxx.sql` 顺序应用未执行的迁移，`schema_migrations` 表记录已应用版本。

升级版本时无需手动操作：

```bash
docker compose down
git pull
docker compose up -d --build
# 启动日志可看到 "schema 迁移已应用：version=N name=..." 行
```

撰写新迁移见 `argus_py/infra/migrations/sql/README.md`。

---

## 8. 安全响应头

middleware 自动注入：

| Header | 值 | 防御 |
|--------|----|------|
| `X-Content-Type-Options` | `nosniff` | MIME sniffing 攻击 |
| `X-Frame-Options` | `DENY` | clickjacking |
| `Referrer-Policy` | `no-referrer` | 内部 URL 泄露 |
| `Cross-Origin-Opener-Policy` | `same-origin` | 跨源 window 引用 |

> 暂未加 CSP：FastAPI `/docs` 与 Element Plus inline 样式与严格 CSP 冲突。若需要可针对前端静态目录单独配置，避开 `/docs`、`/api`。

---

## 9. 上线前验证清单

- [ ] `config/server.yaml` 的 `cors.allow_origins` 包含所有合法 Origin
- [ ] `config/server.yaml` 的 `llm.allow_private_hosts` 列出内网 LLM（若有）
- [ ] `config/.fernet_key` 权限 600（Linux），且已备份至少一份到外置
- [ ] `docker compose up` 后访问 `/health` 返回 200
- [ ] `/docs` 能打开，能创建模型配置并 `/test` 成功（验证 LLM 连通性）
- [ ] 备份脚本通过定时任务每日跑一次
- [ ] WEB_CONCURRENCY 没被 K8s / Helm chart 设成 > 1
- [ ] 若启用 `ARGUS_API_TOKEN`：确认控制台会话输入可用，定时 rotate 流程已就绪
- [ ] 若启用 `rate_limit.enabled` 且部署在反代后：`trust_forwarded: true` 已开
- [ ] 若启用 `events.max_subscribers`：值不低于预期并发用户数的 5 倍
