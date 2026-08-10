# Argus Deployment Guide

[中文文档](deployment.zh.md)

This guide covers private network deployment of Argus: containerization, security hardening (SSRF, CORS, Fernet key), backup and recovery, schema upgrades, and the single-replica constraint.

> Browser automation uses Playwright. Always use the official Playwright Python image (pre-installed with Chromium + libnss / fonts / xvfb). Do not build from a plain base image.

---

## 1. Architecture

```
                      ┌─────────────────┐
            (HTTPS)   │  Reverse Proxy  │   Corporate SSO / Gateway (optional)
    Browser ──────────► │  Nginx / Caddy  │
                      └────────┬────────┘
                               │ (HTTP, internal)
                      ┌────────▼────────┐
                      │  Argus container│   Single replica (hard constraint, see §6)
                      │  uv + uvicorn   │
                      └────────┬────────┘
                               │ volume
                  ┌────────────┴────────────┐
                  │  outputs/data/argus.db  │  WAL mode SQLite
                  │  outputs/screenshots/   │
                  │  outputs/traces/        │
                  │  outputs/backups/       │
                  └─────────────────────────┘
```

---

## 2. Quick Start (Docker Compose)

```bash
# First build and start
docker compose up -d --build

# Check status
docker compose ps
docker compose logs -f argus

# Upgrade
git pull
docker compose build
docker compose up -d
```

After starting, visit `http://<host>:8000/` for the Console, or `/docs` for the OpenAPI / Swagger UI.

### Default network boundary (fail-closed)

The bundled `docker-compose.yml` is tightened by default:

- **Python** publishes its host port only on `127.0.0.1` (`127.0.0.1:8000:8000`),
  so it is not reachable from the LAN. Inside the container uvicorn still binds
  `0.0.0.0`; the compose loopback binding is what limits host-side visibility.
- **Java Analyzer** is only `expose`d to the Compose network (Python reaches it at
  `http://java-analyzer:8081`) and does **not** publish a host port. The Analyzer is
  not a trusted public interface and should only be called by the Python control plane.
- Both sides enforce `allowed-source-roots=/tmp/sources` (Python via
  `ARGUS_WHITEBOX_ALLOWED_SOURCE_ROOTS`, Java via the Dockerfile system property);
  source paths outside the shared directory are rejected by Java (real-path
  validation + symlink-escape refusal). On bare metal the Java default root is
  `${java.io.tmpdir}/argus_sources` (Linux: `/tmp/argus_sources`); the container
  Dockerfile overrides it to `/tmp/sources` to match the shared volume.

To expose the Console to other machines on your intranet, copy
`docker-compose.intranet.example.yml` and set a strong random `ARGUS_API_TOKEN`:

```bash
cp docker-compose.intranet.example.yml docker-compose.intranet.yml
$env:ARGUS_API_TOKEN = (openssl rand -hex 32)
docker compose --profile java -f docker-compose.yml -f docker-compose.intranet.yml up -d
```

The intranet override clears the base compose `ARGUS_BIND_LOOPBACK_ONLY` marker.
Compose refuses to start when `ARGUS_API_TOKEN` is unset, and `argus serve` rejects
tokens shorter than 32 characters or known placeholder values. Non-loopback deployment
is therefore fail-closed. `docker-compose.intranet.yml` is in `.gitignore` to prevent
committing a real Token.

---

## 3. Configuration Baseline (`config/server.yaml`)

> Changes take effect immediately via bind mount — restart the container, no rebuild needed.

### CORS

```yaml
cors:
  allow_origins:
    - https://argus.internal.example.com   # Reverse proxy domain
    - http://localhost:8000                # Local direct access
```

`allow_origins` also determines the **WebSocket Origin whitelist**: cross-origin WS connections from other intranet pages are rejected (intranet phishing defense). CLI / server-to-server requests (no Origin header) are always allowed.

### LLM SSRF Defense

```yaml
llm:
  # Denies RFC1918 private networks / cloud metadata by default
  # Allows localhost, 127.0.0.1
  # Add self-hosted LLM hosts to the whitelist
  allow_private_hosts:
    - 10.10.20.5
    - llm.internal.example.com
```

Unlisted private addresses are rejected on both `/config/models/test` and model config create/update, with error code `MODEL_CONFIG_ERROR`.

### Request Body Size Limit

```yaml
request:
  max_body_size_bytes: 5242880   # Default 5 MB, sufficient for normal prompts/forms
```

### Scheduler Concurrency

```yaml
scheduler:
  concurrency: 4                 # Concurrent tasks per process (not replica count)
```

### Scheduler Queue Capacity

```yaml
scheduler:
  queue_max_size: 32   # Max queued tasks (excluding running); 0 = unbounded (dev only)
```

With a bounded queue, `POST /argus/api/tasks/{id}/start` and `/restart` **fail fast**
when the queue is full: HTTP **503** + `Retry-After` header, error code
`TASK_QUEUE_FULL`, instead of waiting indefinitely for a free slot. The frontend
shows this as "system busy, retry later"; the task stays `pending` and can be
started again later. `restart` on a full queue rolls back the just-created retry
child (no orphan), so the parent regains retry eligibility.

Capacity should be derived from average task duration and acceptable wait time,
not guessed:

```text
queue_max_size ≈ concurrency × acceptable wait ÷ avg task duration
```

Rationale: each task takes ~T; with concurrency C the system drains N queued tasks
in N×T/C; to keep the last queued task's wait ≤ W, N ≤ C×W/T. E.g. concurrency 1,
~2-minute tasks, ~1 hour acceptable wait → 1×60÷2 = 30 ≈ 32 (default).
Heavier tasks / lower wait tolerance → smaller capacity. Watch
`queue_utilization`, `queue_oldest_queued_age_seconds` and `queue_rejected_total`
on `GET /argus/api/metrics` to tune.

`queue_max_size: 0` restores unbounded mode (dev/debug only); `argus serve`
warns at startup.

### WebSocket Subscriber Limit

```yaml
events:
  max_subscribers: 0   # 0 = unlimited (backwards compatible), recommend 5× expected concurrent users
```

Each WS subscription occupies an `asyncio.Queue`. Excessive frontend reconnections may exhaust memory. When the limit is hit, new subscriptions are rejected with `EventBusSubscriberLimitError`, and the frontend receives WebSocket close code **1013 (service overload)** instead of 1008, enabling exponential backoff retry.

### Rate Limiting

```yaml
rate_limit:
  enabled: true
  trust_forwarded: true            # Enable when behind reverse proxy (reads X-Forwarded-For)
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

Implementation is an in-process token bucket, keyed by `(client_ip, rule.name)`. Exceeded requests return **HTTP 429** with `Retry-After` header. The frontend receives `error.code = "RATE_LIMITED"`.

> Single-worker assumption: in-memory state is sufficient. Must switch to Redis / shared storage before multi-replica deployment.

### Optional API Token Authentication

Use when Argus is not behind an SSO reverse proxy but still needs API access control. Set the environment variable:

```bash
ARGUS_API_TOKEN=<generate a 32+ byte random string>
```

When enabled:

| Path Prefix | Token Required |
|-------------|---------------|
| `/health` | No (for reverse proxy / container health checks) |
| `/`, `/assets/...` (SPA static) | No (browser loads HTML without headers) |
| `/argus/api/*` | **Yes** (`Authorization: Bearer <token>`) |
| `/argus/api/ws/*` | **Yes** (browser uses a short-lived single-use `?token=<ticket>`, CLI can use Bearer header) |

The long-lived Token is never placed in a WebSocket URL: the browser first calls
`POST /argus/api/ws/token` (Bearer header) to obtain an HMAC-signed, short-lived
(default 30s), single-use ticket, then opens the WebSocket with `?token=<ticket>`.
This keeps the long-lived Token out of proxy/access logs. Long-lived Tokens are
rejected in WebSocket query strings; CLI/server-to-server clients must use an
`Authorization: Bearer` header to carry the long-lived Token.

After the first 401, the web console prompts for the Token and keeps it only in the current
tab's `sessionStorage`; closing the tab clears it. Screenshots, reports, and debug bundles are
loaded through authenticated requests, so the Token is not embedded in normal HTTP URLs or
frontend build artifacts. Validation uses `hmac.compare_digest`. **Do not commit the token to git.**
For stronger access control, use a reverse proxy with SSO.

### Readiness probe

`/ready` returns **HTTP 503** (not 200) while dependencies are not ready or the lifespan
initialization has not completed, so K8s / Compose / reverse proxies stop routing by status
code; `/health` only indicates process liveness and runs no expensive dependency checks.

Readiness reads the **container state initialized by lifespan** (`app.state.container`)
rather than assembling dependencies on demand through getters:

| Dependency | Ready condition |
|------------|-----------------|
| DB | SQLite reachable (5s TTL cache to avoid probe lock contention) |
| Worker | `health_snapshot()`: started **and** `alive_loops > 0`. If all loops exited abnormally (`crashed_loops` accumulates, `alive_loops` reaches 0) → 503 |
| EventBus | initialized **and** an event loop is present to dispatch (without a loop, `publish` only writes history and cannot push to WebSocket subscribers → not ready) |

`/metrics` additionally exposes `worker_total_loops` / `worker_alive_loops` /
`worker_crashed_loops` / `worker_last_consume_stale_seconds` so monitoring can tell
"worker is running" from "worker loops all exited abnormally while the process is alive".

---

## 4. Sensitive Files

| Path | Purpose | Backup | Permission |
|------|---------|--------|------------|
| `config/.fernet_key` | Model API key encryption/decryption | **Required** | POSIX `chmod 600` (auto-set on startup) |
| `outputs/data/argus.db` | SQLite full data (includes model configs) | Daily | 600 |
| `outputs/data/argus.db-wal` | WAL journal | Copied by backup tool | 600 |

> Argus checks `config/.fernet_key` permissions on startup: if group/others are readable on POSIX, it logs a WARN recommending `chmod 600`. Pay special attention on multi-user Linux SSH servers.

---

## 5. Backup & Recovery

### Daily Backup

```bash
# Inside container, --keep 7 retains only 7 most recent
docker compose exec argus python scripts/backup_db.py --keep 7

# Or from host with same volume mounted
python scripts/backup_db.py --keep 7
```

Backup structure:

```
outputs/backups/20260519T161003Z/
├── argus.db        # Online hot backup (transaction-consistent)
└── .fernet_key     # Decryption key backup (required to decrypt model configs)
```

### Disaster Recovery

1. Stop: `docker compose down`
2. Restore the target timestamp directory's `argus.db` and `.fernet_key` to their original locations (container `/app/outputs/data/` and `/app/config/`)
3. Start: `docker compose up -d`

### Expired Artifact Cleanup

```bash
docker compose exec argus python scripts/cleanup_outputs.py --days 30
```

Default: cleans files older than 30 days from `screenshots / logs / temp / reports / traces`. The `data` and `backups` directories are protected and never cleaned.

---

## 6. Single-Replica Constraint (Important)

Argus currently uses **in-process asyncio.Queue + in-process EventBus**. Multiple workers or replicas cause:

- The same task being consumed by two processes (task duplication)
- WebSocket events only broadcasting to subscribers in the current process (N-1/N event loss)
- `lru_cache` singletons splitting, DI state inconsistencies

Defense measures:

1. `argus serve` checks `WEB_CONCURRENCY` / `UVICORN_WORKERS` env on startup — refuses to start if > 1
2. Lifespan fallback rejection: bypassing the CLI with `uvicorn ... --workers N` raises `RuntimeError` (not a warning)
3. **Cross-process exclusive lock on the outputs directory** (OS file lock, auto-released on process exit): when two processes point at the same DB/outputs, the later one cannot acquire the lock and refuses to start — the last line of defense for unrecognized launch methods
4. `docker-compose.yml` explicitly sets `deploy.replicas: 1` and env `WEB_CONCURRENCY=1`
5. K8s Deployment must use `replicas: 1`, HPA disabled

> Lock file: `outputs/.argus-singleton.lock` (owner info written to a `.owner` sidecar).
> If the file is left behind after the process exits, no manual cleanup is needed — the OS lock was already released with the process, and the next startup rewrites it.

> For horizontal scaling, the queue and EventBus must first be externalized (Redis Streams, NATS, etc.), then replica count can be increased.

---

## 7. Schema Upgrades

`argus_py/infra/migrations/` contains versioned SQL migration scripts. On startup, `apply_migrations()` automatically applies pending migrations in order (`0001_xxx.sql`, `0002_xxx.sql`...). The `schema_migrations` table tracks applied versions.

Upgrade procedure:

```bash
docker compose down
git pull
docker compose up -d --build
# Startup logs show: "schema migration applied: version=N name=..."
```

For writing new migrations, see `argus_py/infra/migrations/sql/README.md`.

---

## 8. Security Headers

Middleware automatically injects:

| Header | Value | Defense |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | MIME sniffing attacks |
| `X-Frame-Options` | `DENY` | Clickjacking |
| `Referrer-Policy` | `no-referrer` | Internal URL leakage |
| `Cross-Origin-Opener-Policy` | `same-origin` | Cross-origin window references |

> CSP is not yet added: FastAPI `/docs` and Element Plus inline styles conflict with strict CSP. Configure CSP per static directory if needed.

---

## 9. Pre-Launch Checklist

- [ ] `config/server.yaml` → `cors.allow_origins` includes all legitimate Origins
- [ ] `config/server.yaml` → `llm.allow_private_hosts` lists internal LLM hosts (if any)
- [ ] `config/.fernet_key` permissions 600 (Linux), and backed up externally
- [ ] `docker compose up` → `/health` returns 200
- [ ] `/docs` opens, model config can be created and `/test` succeeds
- [ ] Backup script scheduled daily
- [ ] `WEB_CONCURRENCY` not set > 1 by K8s / Helm chart
- [ ] If `ARGUS_API_TOKEN` enabled: console session unlock works and rotation workflow is ready
- [ ] If `rate_limit.enabled` and behind reverse proxy: `trust_forwarded: true` is set
- [ ] If `events.max_subscribers` set: value >= 5× expected concurrent users
