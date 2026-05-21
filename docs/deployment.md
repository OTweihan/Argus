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
| `/api/*` | **Yes** (`Authorization: Bearer <token>`) |
| `/ws/*` | **Yes** (browser uses `?token=<token>`, CLI can use Bearer header) |

Validation uses `hmac.compare_digest` for timing-attack resistance. **Do not commit the token to git.** For stronger access control (multi-user, SSO, token rotation), use a reverse proxy.

---

## 4. Sensitive Files

| Path | Purpose | Backup | Permission |
|------|---------|--------|------------|
| `config/.fernet_key` | Model API key encryption/decryption | **Required** | POSIX `chmod 600` (auto-set on startup) |
| `config/llm.env` | Default LLM provider credentials (optional) | Per security level | 600 |
| `outputs/data/argus.db` | SQLite full data | Daily | 600 |
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
2. Lifespan fallback warning (prevents `uvicorn ... --workers N` workarounds)
3. `docker-compose.yml` explicitly sets `deploy.replicas: 1` and env `WEB_CONCURRENCY=1`
4. K8s Deployment must use `replicas: 1`, HPA disabled

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
- [ ] If `ARGUS_API_TOKEN` enabled: frontend build includes token injection, rotation workflow ready
- [ ] If `rate_limit.enabled` and behind reverse proxy: `trust_forwarded: true` is set
- [ ] If `events.max_subscribers` set: value >= 5× expected concurrent users
