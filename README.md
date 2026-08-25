# Argus — AI-Native Web Testing

> Every bug has nowhere to hide.

Stop writing tests. Start describing them.

Argus is an open-source, AI-native test platform that lets you test web
applications by simply describing what you want to check — in plain English.
No Selenium. No Playwright scripts. No page objects to maintain.

```bash
argus run --goal "Submit the contact form and verify the success message" \
          --url "https://example.com/contact"
```

For black-box testing, an LLM plans the browser actions, Playwright executes
them, and a second LLM evaluates whether the goal was met — with screenshots,
DOM snapshots, and structured reports at every step. When something fails,
Argus recovers and retries instead of giving up.

Beyond the browser, Argus performs **white-box analysis** of Java codebases:
a Spring Boot analyzer service powered by JavaParser extracts REST endpoints,
call graphs, execution flows, and feature clusters from your source code.
Black-box runs capture HTTP request evidence that is correlated with those
endpoints — connecting what happens on screen with what happens in code.

**Built for teams that want AI-driven test automation without the script tax.**

[中文文档](README.zh.md)

---

## Overview

Argus bridges the gap between human intent and automated testing. Instead of writing brittle Selenium scripts or complex Playwright code, you express what you want to test in plain language:

```bash
argus run --goal "Test the login form — check required fields and error messages" --url "https://example.com/login"
```

The system handles planning, execution, failure recovery, evidence collection (screenshots, DOM snapshots, HTTP request evidence), and report generation. Built for teams that want AI-driven test automation without maintaining script-heavy test suites.

### When to use Argus

| Scenario | Description |
|----------|-------------|
| **Exploratory testing** | Quickly verify a page renders correctly, links work, forms submit |
| **Regression smoke tests** | Reuse saved auth states to check post-login pages across deployments |
| **Form & login flow validation** | Test validation rules, error states, and submission flows |
| **Pre-release sanity checks** | Automate a batch of URL checks before a release |
| **Demo / prototype QA** | Get test coverage on early-stage products where UI changes frequently |
| **Java codebase insight** | Extract REST endpoints, call graphs, and execution flows from Java repositories |
| **Black-box ↔ white-box correlation** | Map UI-level HTTP traffic back to the code paths that serve it |

---

## Features

- **Natural language test execution** — Describe what to test; Argus figures out the steps.
- **LLM-driven Planner & Evaluator** — Two specialized prompts: one plans browser actions, the other judges if the goal is met. Both support business-rule extensions per project or task.
- **Self-healing execution** — Failed actions don't abort the task. Argus records the failure, re-observes the page, and retries with failure-aware planning (default 2 recovery attempts).
- **Playwright browser automation** — Chromium, Firefox, WebKit. Supports goto, click, type, select, wait, screenshot, and DOM snapshots with smart selector recommendations.
- **White-box static analysis** — `argus analyze` snapshots a Git repo or local directory and sends it to a Java Analyzer service (Spring Boot + JavaParser + Maven classpath resolution). Scopes: full analysis, incremental changes, specific modules, endpoint extraction, call graph, execution flows, feature clustering. Results include REST endpoints, call graphs, findings, execution flows, and feature clusters with HTML/JSON reports.
- **Black-white-box correlation** — HTTP requests captured during black-box runs are matched against white-box endpoints, linking UI behavior to server-side code paths with auditable correlation runs.
- **Browser auth state management** — Save login state (cookies, localStorage) once and reuse across tasks via `argus auth save / list` and `--auth-state`.
- **Structured reporting** — HTML reports (human-readable with collapsible steps, screenshots, click-to-enlarge) and JSON reports (machine-readable) for black-box and white-box tasks alike.
- **Task observability** — Per-task execution timeline persisted in SQLite, real-time WebSocket streaming, LLM call traces (full prompt/response/error), and ZIP debug bundles for offline analysis.
- **Model configuration management** — Multiple LLM provider configs stored in SQLite with encrypted API keys (Fernet), assignable per task.
- **Prompt business extensions** — Append custom rules to Planner/Evaluator prompts at the project or task level without touching built-in templates.
- **Sensitive data redaction** — Recursively masks api_key, password, token, authorization, etc. in logs, traces, and debug bundles.
- **Web Console** — Vue 3 + Element Plus SPA for managing projects, tasks, models, viewing black-box/white-box reports, execution timeline, LLM debug tabs, and correlation summaries.
- **REST API + WebSocket** — Full RESTful API with OpenAPI docs, real-time task event streaming via WebSocket.
- **Docker deployment** — Containerized with SSRF protection, CORS/WebSocket origin validation, rate limiting, optional API token auth, automated DB backups, and schema migrations.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+ and pnpm (only for frontend development)
- Playwright browser environment
- An OpenAI Chat Completions-compatible LLM API

### Install

Install Argus with its browser extra:

```bash
pip install -e ".[browser]"
```

Install Playwright Chromium:

```bash
playwright install chromium
```

Verify the CLI:

```bash
argus --version
```

> Repository contributors can manage the environment with
> [uv](https://docs.astral.sh/uv/) instead — see *One-command Local Development*.

### One-command Local Development

A zero-dependency Node.js process manager starts the Python API, Vite dev
server, and Java Analyzer together, aggregating logs in your terminal.

Prepare a Python 3.11+ environment with the project dependencies installed,
plus the frontend dependencies:

```bash
uv sync --extra browser                         # recommended (requires uv); without uv: pip install -e ".[browser]"
pnpm --dir frontend install --frozen-lockfile   # first time only
node scripts/dev.mjs --check                    # verify toolchain & ports
node scripts/dev.mjs                            # start all services
```

Then open the frontend at <http://127.0.0.1:5173>. Python and the frontend
hot-reload; restart the manager after changing Java sources. Logs are written
to `outputs/logs/dev/<start-time>/` and may contain sensitive runtime data.

### Configure LLM

```bash
argus config llm
```

This walks you through API Key, endpoint, and model name. Configuration is saved to the database (encrypted).

Verify connectivity:

```bash
argus llm check
```

### Run Your First Test

```bash
argus run --goal "Open the page and take a screenshot" --url "https://httpbin.org"
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `argus run --goal <text> --url <url>` | Execute a black-box test task |
| `argus analyze --repo <url>` / `argus analyze --source-path <dir>` | Execute a white-box analysis task |
| `argus serve` | Start the FastAPI web server |
| `argus run --create-only` | Create a task snapshot without execution |
| `argus browser check --url <url>` | Debug browser capabilities |
| `argus auth save --url <url>` | Save browser login state |
| `argus auth list` | List saved browser login states |
| `argus llm check` | Verify LLM API connectivity |
| `argus config llm` | Interactive LLM configuration |
| `argus config llm --advanced` | Configure advanced parameters (max tokens, temperature, retries) |

Global options: `-v` / `-vv` raise log level to INFO / DEBUG.

### `argus run` Options

| Option | Description |
|--------|-------------|
| `--goal` | Test goal in natural language |
| `--url` | Target URL |
| `--headed` | Show browser window during execution |
| `--auth-state <name>` | Reuse saved browser login state |
| `--no-screenshot` | Disable step screenshots |
| `--create-only` | Create task snapshot, don't execute |
| `--project <id>` | Associate task with a project |
| `--max-steps <n>` | Override max planning steps |
| `--timeout <s>` | Override execution timeout |
| `--planner-extension <file>` | Custom rules for Planner prompt |
| `--evaluator-extension <file>` | Custom rules for Evaluator prompt |

### `argus analyze` Options

| Option | Description |
|--------|-------------|
| `--repo <url>` | Git repository URL (mutually exclusive with `--source-path`) |
| `--source-path <dir>` | Local source directory (mutually exclusive with `--repo`) |
| `--branch <name>` | Branch to analyze (with `--repo` only) |
| `--scope <s>` | `all` (default), `changed`, `modules`, `endpoints`, `callgraph`, `flows`, `clusters` |
| `--project <id>` | Associate task with a project |
| `--target-modules <m...>` | Target Maven modules (required for `--scope modules`) |
| `--classpath-mode <mode>` | Classpath strategy: `auto` / `cache-only` / `maven` / `source-only` |
| `--maven-executable`, `--maven-settings`, `--local-repository`, `--maven-offline`, `--maven-classpath-file`, `--prepare-reactor` | Maven classpath resolution tuning |

---

## Web Console & API

Start the web server:

```bash
argus serve
# Opens at http://localhost:8000
```

The Web Console (Vue 3 SPA) provides:

- **Dashboard** — Overview of projects and tasks
- **Projects** — CRUD, prompt extension editor with live system prompt preview
- **Tasks** — Create, start, stop; view black-box reports, white-box reports, execution timeline, LLM debug traces, and black-white-box correlation summaries
- **Models** — Manage LLM provider configurations, test connectivity

### Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET/POST | `/argus/api/projects` | List / create projects |
| GET/POST | `/argus/api/tasks` | List / create tasks |
| POST | `/argus/api/tasks/{id}/start` | Start task execution |
| POST | `/argus/api/tasks/{id}/stop` | Stop running task |
| GET | `/argus/api/tasks/{id}/report` | Get task report (HTML or JSON) |
| GET | `/argus/api/tasks/{id}/events` | Get execution timeline |
| GET | `/argus/api/tasks/{id}/llm-traces` | Get LLM call traces |
| GET | `/argus/api/tasks/{id}/debug-bundle` | Download debug bundle (ZIP) |
| GET | `/argus/api/tasks/{id}/analysis-runs` | List white-box analysis runs of a task |
| GET | `/argus/api/correlation-runs/{id}` | Get correlation run detail (plus `attempts`, `summary`, evidence endpoints) |
| GET/POST | `/argus/api/config/models` | Manage model configurations |
| WS | `/argus/api/ws/tasks/{id}` | Real-time task events |
| — | `/docs` | OpenAPI / Swagger UI |

---

## Architecture

```
┌───────────────────────────────────────────────────────┐
│                      CLI (argus)                      │
│ run │ analyze │ serve │ browser │ auth │ llm │ config │
└───────────┬───────────────────────────────────────────┘
            │
┌───────────▼───────────────────────────────────────────┐
│                  FastAPI Web Server                   │
│   REST API │ WebSocket │ Vue 3 Console (SPA)          │
└───────────┬───────────────────────────────────────────┘
            │
┌───────────▼───────────────────────────────────────────┐
│                      Task Runner                      │
│                                                       │
│ ┌─ Black-box Agent ──────┐    ┌─ White-box ─────────┐ │
│ │ Planner → Executor →   │    │ Source snapshot →   │ │
│ │ Evaluator (LLM loop)   │    │ HTTP JSON → Java    │ │
│ │ Playwright execution + │    │ Analyzer (Spring    │ │
│ │ HTTP evidence capture  │    │ Boot + JavaParser)  │ │
│ └───────────┬────────────┘    └──────────┬──────────┘ │
│             └────── Correlation ─────────┘            │
└───────────┬───────────────────────────────────────────┘
            │
┌───────────▼───────────────────────────────────────────┐
│                    Infrastructure                     │
│ SQLite │ File System │ Event Bus │ Task Queue         │
└───────────────────────────────────────────────────────┘
```

**Black-box execution flow:**

1. **Planner** (LLM) receives the goal + page snapshot, outputs next browser action
2. **Executor** runs the action via Playwright, captures screenshot, DOM snapshot, and HTTP request evidence
3. **Evaluator** (LLM) assesses whether the goal is achieved
4. If not satisfied, loop back to Planner with updated context
5. On failure, recovery logic re-observes the page and re-plans (up to 2 retries)
6. When done, generate HTML + JSON reports

**White-box analysis flow:**

1. Python snapshots the source (Git clone or local copy)
2. The source is sent to the Java Analyzer over a versioned HTTP/JSON contract
3. JavaParser + Maven classpath resolution produce endpoints, call graphs, findings, execution flows, and clusters
4. Results are persisted and rendered as white-box HTML/JSON reports

**Correlation:** black-box HTTP request evidence is matched against extracted endpoints, producing auditable correlation runs that link UI behavior to server-side code.

---

## Prompt Extension System

Argus separates built-in prompts from user extensions:

- **Built-in templates** (`argus_py/llm/prompts/`) — Planner and Evaluator prompts shipped with the package, **not overridable**.
- **Business extensions** — Append custom rules per project or per task via `parameters.prompt_extensions.{planner,evaluator}`.

Concatenation order: `Built-in → Project extension → Task extension`

This allows tailoring test behavior per application without forking the codebase. The Web Console provides a Markdown editor with live system-prompt preview.

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Python | 3.11+ (managed with uv + `uv.lock`) |
| LLM API | OpenAI Chat Completions-compatible |
| Browser | Playwright (Chromium) |
| Web framework | FastAPI + Uvicorn |
| Frontend | TypeScript + Vue 3 + Element Plus + Vite |
| Static analysis engine | Java 21 · Spring Boot · JavaParser |
| Reporting | Jinja2 (HTML) + JSON |
| Database | SQLite (WAL mode) |
| Observability | SQLite events + JSONL traces + WebSocket |
| Deployment | Docker / Docker Compose |

---

## Project Structure

```
argus/
├── argus_py/
│   ├── cli/           # CLI entry points and interactive prompts
│   ├── api/           # FastAPI app, routes, schemas, middleware, static hosting
│   ├── core/          # Constants, paths, enums, exceptions, IDs
│   ├── config/        # Configuration loading, model config service, SQLite storage
│   ├── llm/           # LLM client, provider adapters, prompts, parsing, retry
│   ├── observability/ # Audit, LLM traces
│   ├── redaction/     # Sensitive data masking utilities
│   ├── task/          # Task model, state machine, SQLite storage, timeline, lifecycle
│   ├── execution/     # Task runner facade
│   ├── runtime/       # DI container (composition root)
│   ├── blackbox/      # Planner, Executor, Evaluator, recovery
│   ├── browser/       # Playwright lifecycle, actions, selectors, snapshots
│   ├── whitebox/      # White-box client, source resolver, runner, projection
│   ├── analysis/      # Analysis run model, scopes, quality issues
│   ├── correlation/   # Black-white-box correlation service and evidence models
│   ├── report/        # Report model, HTML/JSON export
│   ├── project/       # Project model, SQLite storage, CRUD
│   ├── infra/         # SQLite infra, migrations, task queue, event bus
│   └── utils/         # Logging, file IO, JSON helpers
├── frontend/          # TypeScript + Vite + Vue 3 SPA source
├── java_analyzer/     # Spring Boot analyzer service (JavaParser + Maven classpath)
├── config/            # Configuration files (logging.yaml, server.yaml)
├── docs/              # Documentation (architecture, guides, CLI, deployment)
├── tests/             # Unit, contract, and integration tests
├── examples/          # Example task JSON files
├── scripts/           # Dev process manager (dev.mjs), backup, cleanup utilities
└── outputs/           # Runtime artifacts (reports, screenshots, traces) — gitignored
```

---

## Deployment

Argus supports Docker-based deployment for private networks. The core stack
runs with a single container; add `--profile java` to include the Java
Analyzer for white-box analysis:

```bash
docker compose up -d --build                      # core (black-box + console)
docker compose --profile java up -d --build       # core + Java Analyzer
```

See the [deployment guide](docs/deployment.md) for:

- Docker Compose setup and the intranet override file
- SSRF protection and CORS configuration
- API token authentication
- Automated DB backups
- Schema migrations
- Security hardening

---

## Documentation

| Document | Content |
|----------|---------|
| [Architecture](docs/architecture.md) | Architecture baseline, layering, and evolution constraints |
| [User Guide](docs/guide.md) | Configuration, Web Console, prompt extensions, reports, troubleshooting |
| [CLI Reference](docs/cli.md) | Full command and option reference |
| [Deployment](docs/deployment.md) | Docker deployment and operations |
| [Logging](docs/logging.md) | Logging and observability conventions |

---

## License

MIT
