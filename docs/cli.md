# Argus CLI Reference

[中文文档](cli.zh.md)

## Overview

Argus ships as a single `argus` CLI command with several subcommands. `argus run` executes black-box browser tests, while `argus analyze` runs white-box static analysis on Java codebases. All commands share the global options.

### Global Options

| Option | Description |
|--------|-------------|
| `--version` | Show version and exit |
| `-v` | Verbose output (INFO level) |
| `-vv` | Very verbose output (DEBUG level) |
| `--help` | Show help message and exit |

---

## `argus run` — Execute Black-box Test Task

The core command. Describe a test goal in natural language, and Argus handles planning, execution, and reporting.

```bash
argus run --goal "Open the page and take a screenshot" --url "https://httpbin.org"
```

### Options

| Option | Required | Description |
|--------|----------|-------------|
| `--goal` / `-g` | Yes | Test goal in natural language |
| `--url` / `-u` | Yes | Target URL to test |
| `--headed` | No | Show browser window during execution (default: headless) |
| `--auth-state` | No | Reuse saved browser login state (name or JSON file path) |
| `--no-screenshot` | No | Disable step screenshots |
| `--create-only` | No | Create a task snapshot without executing it |
| `--project` | No | Associate the task with a project ID |
| `--max-steps` | No | Override maximum planning steps |
| `--timeout` | No | Override execution timeout in seconds |
| `--planner-extension` | No | Path to a Markdown file with custom Planner rules |
| `--evaluator-extension` | No | Path to a Markdown file with custom Evaluator rules |

### Execution Strategies

When `--max-steps` and `--timeout` are not specified, Argus auto-infers limits based on the goal:

| Task Type | Max Steps | Timeout |
|-----------|-----------|---------|
| Simple visit / screenshot / accessibility check | 6 | 180s |
| Normal black-box task | 12 | 300s |
| Login / form / submission / workflow task | 20 | 600s |

### Failure Recovery

Failed actions do not abort the task. The system records the failure, re-observes the page, and lets the Planner retry with awareness of the failure history (default 2 recovery attempts). After all recovery attempts are exhausted, the task finishes with a failure status but still generates a report.

### Examples

```bash
# Basic screenshot
argus run --goal "Open the page and take a screenshot" --url "https://httpbin.org"

# Multi-step workflow
argus run --goal "Open homepage → click link → fill form → submit → verify result" \
  --url "https://demo.playwright.dev/todomvc"

# Login page validation
argus run --goal "Test the login form — check required fields, validation errors, and failed login message" \
  --url "https://example.com/login"

# With browser window visible
argus run --goal "Open page and screenshot" --url "https://httpbin.org" --headed

# Reusing saved auth state
argus run --auth-state example.com \
  --goal "Check the profile page loads correctly" \
  --url "https://example.com/profile"

# Task snapshot only (no execution)
argus run --goal "Open page and screenshot" --url "https://httpbin.org" --create-only

# Disable screenshots
argus run --goal "Check page title" --url "https://httpbin.org" --no-screenshot

# Manual limits override
argus run --goal "Complex form flow" --url "https://example.com/form" --max-steps 5 --timeout 180
```

### Output

After completion, Argus prints the task status, step count, issue count, and report path:

- **Reports:** `outputs/reports/<task_id>/index.html` and `outputs/reports/<task_id>/report.json`
- **Screenshots:** `outputs/screenshots/<task_id>/` (one per execution step)

---

## `argus analyze` — Execute White-box Analysis

Run a static analysis task on a Java codebase. Argus snapshots the source (Git clone or local copy), sends it to the Java Analyzer service (Spring Boot + JavaParser + Maven classpath resolution), and generates an HTML/JSON report.

### Prerequisites

- A reachable Java Analyzer service — default `http://localhost:8081`, override with `ARGUS_JAVA_ANALYZER_URL` (Docker Compose: start it with `--profile java`)
- The source path must be visible to the analyzer process (container deployments use the shared source volume; paths outside the allowed source roots are rejected)

### Usage

```bash
# Analyze a Git repository (full analysis)
argus analyze --repo https://github.com/user/project.git

# Analyze a local directory
argus analyze --source-path /path/to/project

# Analyze a specific branch
argus analyze --repo https://github.com/user/project.git --branch main

# Extract REST endpoints only, restricted to given Maven modules
argus analyze --source-path /path/to/project --scope endpoints \
  --target-modules app-api app-web
```

### Options

| Option | Description |
|--------|-------------|
| `--repo <url>` | Git repository URL (mutually exclusive with `--source-path`) |
| `--source-path <dir>` | Local source directory (mutually exclusive with `--repo`) |
| `--branch <name>` | Branch to analyze (`--repo` only) |
| `--scope <s>` | `all` (default), `changed`, `modules`, `endpoints`, `callgraph`, `flows`, `clusters` |
| `--project <id>` | Associate the analysis task with a project |
| `--target-modules <m...>` | Target Maven modules, space separated (required for `--scope modules`) |
| `--classpath-mode <mode>` | Classpath strategy: `auto` (smart fallback), `cache-only`, `maven`, `source-only` |
| `--prepare-reactor` | Run `mvn install -DskipTests` before classpath generation to prepare reactor-internal modules |
| `--maven-classpath-file` | classpath file path (relative to the project root) |
| `--maven-executable` | Maven executable path |
| `--maven-settings` | Maven settings.xml path |
| `--local-repository` | Local Maven repository path |
| `--maven-offline` | Run Maven in offline mode |

### Analysis Scopes

| Scope | Content |
|-------|---------|
| `all` | Full analysis: endpoints, call graph, findings, execution flows, clusters |
| `changed` | Incremental analysis of changes |
| `modules` | Restrict analysis to the specified Maven modules |
| `endpoints` | REST endpoint extraction only |
| `callgraph` | Call graph only |
| `flows` | Execution flows only |
| `clusters` | Feature clustering only |

### Output

The task result prints status and report paths. Reports are written under `outputs/reports/<task_id>/`. Optional passes (flows/clusters) degrade gracefully instead of failing the job when they error — degradations are recorded in the analyzer diagnostics and surfaced in the report and CLI output.

---

## `argus serve` — Start Web Server

Start the FastAPI web server with the Web Console and REST API.

```bash
argus serve
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8000` | Port number |
| `--reload` | disabled | Enable hot-reload for development |

### What You Get

- **Web Console:** `http://localhost:8000/` — Vue 3 SPA for managing projects, tasks, and models
- **REST API:** `http://localhost:8000/argus/api/` — Full RESTful API
- **OpenAPI Docs:** `http://localhost:8000/docs` — Interactive Swagger UI
- **WebSocket:** `ws://localhost:8000/argus/api/ws/tasks/{id}` — Real-time task events

---

## `argus browser check` — Debug Browser Capabilities

Verify Playwright browser integration and debug selectors, with optional page interaction.

```bash
argus browser check --url "https://httpbin.org"
```

### Options

| Option | Description |
|--------|-------------|
| `--url` | URL to open |
| `--headed` | Show browser window |
| `--screenshot` | Custom screenshot save path |
| `--fill-selector` | CSS selector to fill |
| `--fill-text` | Text to type into the fill target |
| `--click` | Selector to click |
| `--wait-ms` | Extra wait time before screenshot (ms) |

### Examples

```bash
# Basic check
argus browser check --url "https://httpbin.org"

# With window visible
argus browser check --url "https://httpbin.org" --headed

# Custom screenshot path
argus browser check --url "https://httpbin.org" --screenshot "outputs/screenshots/debug.png"

# Fill a form and click
argus browser check --url "https://httpbin.org/forms/post" \
  --fill-selector "input[name='custname']" --fill-text "WeiHan" \
  --click "text=Submit"
```

The browser wrapper automatically waits for page stabilization. `--wait-ms` is only needed as an extra debug parameter.

---

## `argus auth` — Browser Login State Management

Save and reuse browser authentication state (cookies, localStorage) across test tasks.

### `argus auth save`

Open a browser window for manual login, then save the session state.

```bash
argus auth save --url "https://example.com/login"
```

| Option | Description |
|--------|-------------|
| `--url` | Login page URL |
| `--name` | Custom state name (default: auto-derived from hostname) |

The command opens the browser in headed mode. After logging in, return to the terminal and press Enter. The state is saved to `config/browser-states/<name>.json`.

```bash
# Custom name
argus auth save --name example-admin --url "https://example.com/login"
```

Port handling: if the URL contains a port, the name replaces `:` with `-` (e.g., `http://10.18.90.80:8580/login` saves as `config/browser-states/10.18.90.80-8580.json`).

### `argus auth list`

List all saved login states.

```bash
argus auth list
```

Shows state name, associated site, last modified time, reuse command, and file path.

### Reusing Auth State

Pass `--auth-state` to `argus run`:

```bash
argus run --auth-state example.com --goal "Check profile page" --url "https://example.com/profile"
```

`--auth-state` accepts either a saved state name or a direct JSON file path.

> Auth state files contain cookies, localStorage, and session data. They are excluded from git via `.gitignore`. Handle them as sensitive files — do not commit or share.

---

## `argus llm check` — Verify LLM Connectivity

Test the configured LLM API with a fixed low-token prompt (no user input to avoid unnecessary token consumption).

```bash
argus llm check
```

### Options

| Option | Description |
|--------|-------------|
| `--timeout` | Override wait time (default: 60s) |
| `--model` | Temporarily override model name |
| `--base-url` | Temporarily override API base URL |

### Examples

```bash
# Default check
argus llm check

# Longer timeout for slow endpoints
argus llm check --timeout 90

# Override model and URL temporarily
argus llm check --model "qwen3.5-plus" --base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

---

## `argus config llm` — Configure LLM

Interactive configuration for the LLM API connection.

```bash
argus config llm
```

Prompts for:
- API Key (masked input with asterisks)
- Base URL (endpoint)
- Model name

Configuration is saved to the database (API key encrypted).

### Advanced Configuration

```bash
argus config llm --advanced
```

Additionally prompts for:
- Max output tokens
- Temperature
- Max retry count

First-time setup uses sensible defaults for advanced parameters. Run with `--advanced` only when you need to tune these.

---

## `argus --version`

```bash
argus --version
```

Prints the current version number.
