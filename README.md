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

An LLM plans the browser actions, Playwright executes them, and a second LLM
evaluates whether the goal was met — with screenshots, DOM snapshots, and
structured reports at every step. When something fails, Argus recovers and
retries instead of giving up.

**Built for teams that want AI-driven test automation without the script tax.**

[中文文档](README.zh.md)

---

## Overview

Argus bridges the gap between human intent and automated testing. Instead of writing brittle Selenium scripts or complex Playwright code, you express what you want to test in plain language:

```bash
argus run --goal "Test the login form — check required fields and error messages" --url "https://example.com/login"
```

The system handles planning, execution, failure recovery, evidence collection (screenshots, DOM snapshots), and report generation. Built for teams that want AI-driven test automation without maintaining script-heavy test suites.

### When to use Argus

| Scenario | Description |
|----------|-------------|
| **Exploratory testing** | Quickly verify a page renders correctly, links work, forms submit |
| **Regression smoke tests** | Reuse saved auth states to check post-login pages across deployments |
| **Form & login flow validation** | Test validation rules, error states, and submission flows |
| **Pre-release sanity checks** | Automate a batch of URL checks before a release |
| **Demo / prototype QA** | Get test coverage on early-stage products where UI changes frequently |

---

## Features

- **Natural language test execution** — Describe what to test; Argus figures out the steps.
- **LLM-driven Planner & Evaluator** — Two specialized prompts: one plans browser actions, the other judges if the goal is met. Both support business-rule extensions per project or task.
- **Self-healing execution** — Failed actions don't abort the task. Argus records the failure, re-observes the page, and retries with failure-aware planning (default 2 recovery attempts).
- **Playwright browser automation** — Chromium, Firefox, WebKit. Supports goto, click, type, select, wait, screenshot, and DOM snapshots with smart selector recommendations.
- **Browser auth state management** — Save login state (cookies, localStorage) once and reuse across tasks via `argus auth save / list` and `--auth-state`.
- **Structured reporting** — HTML reports (human-readable with collapsible steps, screenshots, click-to-enlarge) and JSON reports (machine-readable) for every task.
- **Task observability** — Per-task execution timeline persisted in SQLite, real-time WebSocket streaming, LLM call traces (full prompt/response/error), and ZIP debug bundles for offline analysis.
- **Model configuration management** — Multiple LLM provider configs stored in SQLite with encrypted API keys (Fernet), assignable per task.
- **Prompt business extensions** — Append custom rules to Planner/Evaluator prompts at the project or task level without touching built-in templates.
- **Sensitive data redaction** — Recursively masks api_key, password, token, authorization, etc. in logs, traces, and debug bundles.
- **Web Console** — Vue 3 + Element Plus SPA for managing projects, tasks, models, and viewing reports with execution timeline and LLM debug tabs.
- **REST API + WebSocket** — Full RESTful API with OpenAPI docs, real-time task event streaming via WebSocket.
- **Docker deployment** — Containerized with SSRF protection, CORS/WebSocket origin validation, rate limiting, optional API token auth, automated DB backups, and schema migrations.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Playwright browser environment
- An OpenAI Chat Completions-compatible LLM API

### Install

```bash
pip install -e ".[dev]"
argus --version
```

Install Playwright Chromium:

```bash
playwright install chromium
```

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
| `argus serve` | Start the FastAPI web server |
| `argus run --goal <text> --url <url>` | Execute a black-box test task |
| `argus run --create-only` | Create a task snapshot without execution |
| `argus browser check --url <url>` | Debug browser capabilities |
| `argus auth save --url <url>` | Save browser login state |
| `argus auth list` | List saved browser login states |
| `argus llm check` | Verify LLM API connectivity |
| `argus config llm` | Interactive LLM configuration |
| `argus config llm --advanced` | Configure advanced parameters (max tokens, temperature, retries) |

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
- **Tasks** — Create, start, stop; view reports, execution timeline, and LLM debug traces
- **Models** — Manage LLM provider configurations, test connectivity

### Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET/POST | `/api/v1/projects` | List / create projects |
| GET/POST | `/api/v1/tasks` | List / create tasks |
| POST | `/api/v1/tasks/{id}/start` | Start task execution |
| POST | `/api/v1/tasks/{id}/stop` | Stop running task |
| GET | `/api/v1/tasks/{id}/report` | Get task report (HTML or JSON) |
| GET | `/api/v1/tasks/{id}/events` | Get execution timeline |
| GET | `/api/v1/tasks/{id}/llm-traces` | Get LLM call traces |
| GET | `/api/v1/tasks/{id}/debug-bundle` | Download debug bundle (ZIP) |
| GET/POST | `/api/v1/config/models` | Manage model configurations |
| WS | `/api/v1/ws/tasks/{id}` | Real-time task events |
| — | `/docs` | OpenAPI / Swagger UI |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   CLI (argus)                    │
│  run │ serve │ browser │ auth │ llm │ config     │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              FastAPI Web Server                  │
│  REST API │ WebSocket │ Vue 3 Console (SPA)      │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              Black-box Agent                     │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐       │
│  │ Planner │─►│ Executor │─►│ Evaluator │       │
│  │  (LLM)  │  │Playwright│  │  (LLM)    │       │
│  └─────────┘  └──────────┘  └───────────┘       │
│         │           │              │             │
│         ▼           ▼              ▼             │
│   Step Logs    Screenshots    Issue Records      │
└──────────┬──────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              Infrastructure                      │
│  SQLite │ File System │ Event Bus │ Task Queue   │
└─────────────────────────────────────────────────┘
```

**Execution flow:**

1. **Planner** (LLM) receives the goal + page snapshot, outputs next browser action
2. **Executor** runs the action via Playwright, captures screenshot and DOM snapshot
3. **Evaluator** (LLM) assesses whether the goal is achieved
4. If not satisfied, loop back to Planner with updated context
5. On failure, recovery logic re-observes the page and re-plans (up to 2 retries)
6. When done, generate HTML + JSON reports

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
| Python | 3.11+ |
| LLM API | OpenAI Chat Completions-compatible |
| Browser | Playwright (Chromium) |
| Web framework | FastAPI + Uvicorn |
| Frontend | TypeScript + Vue 3 + Element Plus + Vite |
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
│   ├── observability/ # Audit, redaction, LLM traces
│   ├── task/          # Task model, state machine, SQLite storage, timeline, lifecycle
│   ├── blackbox/      # Planner, Executor, Evaluator, recovery
│   ├── browser/       # Playwright lifecycle, actions, selectors, snapshots
│   ├── report/        # Report model, HTML/JSON export
│   ├── project/       # Project model, SQLite storage, CRUD
│   ├── infra/         # SQLite infra, migrations, task queue, event bus
│   ├── execution/     # Task runner facade
│   ├── runtime/       # DI container
│   └── whitebox/      # Java white-box analysis stub (planned)
├── frontend/          # TypeScript + Vite + Vue 3 SPA source
├── config/            # Configuration files (logging.yaml, server.yaml)
├── docs/              # Documentation
├── tests/             # Unit, contract, and integration tests
├── examples/          # Example task JSON files
├── scripts/           # Utility scripts (backup, cleanup)
├── outputs/           # Runtime artifacts (reports, screenshots, traces) — gitignored
└── java_analyzer/     # Java analyzer submodule stub (planned)
```

---

## Deployment

Argus supports Docker-based deployment for private networks. See the [deployment guide](docs/deployment.md) for:

- Docker Compose setup
- SSRF protection and CORS configuration
- API token authentication
- Automated DB backups
- Schema migrations
- Security hardening

---

## License

MIT
