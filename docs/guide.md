# Argus User Guide

[中文文档](guide.zh.md)

This guide covers everything you need to use Argus effectively — from configuration and the Web Console to prompt extensions, report interpretation, and troubleshooting.

---

## Table of Contents

1. [Configuration](#configuration)
2. [Web Console](#web-console)
3. [Prompt Extension System](#prompt-extension-system)
4. [Browser Auth State Management](#browser-auth-state-management)
5. [Reports & Execution](#reports--execution)
6. [Task Observability](#task-observability)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)

---

## Configuration

### LLM Configuration

Argus needs an OpenAI Chat Completions-compatible LLM API. Configure it interactively:

```bash
argus config llm
```

This saves to the database (API key encrypted). You can manage multiple profiles later via the Web Console.

To verify connectivity:

```bash
argus llm check
```

#### Environment File Format

```env
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

#### Advanced Parameters

```bash
argus config llm --advanced
```

Additional settings: max tokens (default: 4096), temperature (default: 0), max retries (default: 3).

### Server Configuration

Server settings live in `config/server.yaml`:

- **CORS origins** — allowed frontend domains
- **Rate limiting** — per-route request throttling
- **SSRF protection** — allowed private LLM hosts
- **Observability** — toggle request logging, audit, LLM traces
- **Scheduler concurrency** — max concurrent tasks (default: 4)
- **WebSocket limits** — max subscribers per event bus

Edit this file and restart `argus serve` for changes to take effect.

### Model Configuration (via Web Console)

Multiple LLM provider configurations can be stored in SQLite with encrypted API keys:

1. Navigate to **Models** in the Web Console
2. Click **Add Model** and enter API endpoint, model name, and API key
3. Click **Test Connection** to verify
4. Assign the model config to a task when creating it

API keys are encrypted at rest using a Fernet key stored at `config/.fernet_key`. The key is auto-generated on first `argus serve` start.

---

## Web Console

The Web Console is a Vue 3 SPA served by Argus at `http://localhost:8000/` when running `argus serve`.

### Building the Frontend

The frontend source is at `frontend/`. Build it before first launch:

```bash
cd frontend
pnpm install
pnpm build
cd ..
argus serve
```

After the initial build:
- Python-only changes → just restart `argus serve`, no rebuild needed
- Frontend changes → run `pnpm build` again, then restart `argus serve`

### Pages

#### Dashboard

Shows an overview of projects and recent tasks with their status.

#### Projects

Manage test projects. Each project can have:
- A name and description
- Custom prompt extensions (see [Prompt Extension System](#prompt-extension-system))
- Associated tasks

#### Tasks

The task management center. Features:
- **Create task** — set goal, URL, project association, model config, and prompt extensions
- **Task list** — filter by status, project, search by goal
- **Task detail** — three tabs:

  **Report Tab** — View the HTML report inline with collapsible steps, screenshots, and issues.

  **Execution Timeline** — See the full lifecycle: task created → queued → started → each Planner/Executor/Evaluator cycle → completed. Events stream in real-time via WebSocket. Persisted in SQLite's `task_events` table.

  **LLM Debug Tab** — Inspect every LLM call made during the task:
  - Phase, event, model, host, duration, token usage
  - System Prompt
  - Input Payload (full API request)
  - Raw Response (full API response)
  - Parsed Result (structured output after JSON parsing)
  - Errors and parse failures

#### Models

Manage LLM provider configurations.

---

## Prompt Extension System

Argus separates built-in prompts from user-defined business rules.

### Architecture

```
Concatenation order:  Built-in → Project Extension → Task Extension
```

- **Built-in templates** at `argus_py/llm/prompts/` — hard contracts with input fields, output JSON schemas, and safety boundaries. **Cannot be overridden.**
- **Project extensions** — custom rules stored in the project's `parameters.prompt_extensions.{planner,evaluator}`.
- **Task extensions** — custom rules stored in the task's `parameters.prompt_extensions.{planner,evaluator}`, appended after project extensions.

Each marker (`## 业务扩展` / `## Business Extensions`) in the built-in templates serves as the insertion point for extensions.

### Usage via CLI

```bash
argus run --goal "..." --url "..." \
  --planner-extension ./my-rules/planner.md \
  --evaluator-extension ./my-rules/evaluator.md
```

### Usage via Web Console

In the Project or Task create/edit dialog, expand the **Prompt Extensions** panel:

- Two tabs: **Planner** and **Evaluator**
- Markdown editor on the left, rendered preview on the right
- A **Preview Full System Prompt** button at the bottom calls `POST /argus/api/prompts/preview` (with 600ms debounce) to show the concatenated built-in + project + task prompt

### Example Extensions

**Planner extension** (for a specific app):
```markdown
## Project-Specific Rules
- Dangerous button keywords: void, withdraw, open-account
- Login page is always at /auth/signin
- Do not click elements with class "disabled"
```

**Evaluator extension:**
```markdown
## Evaluation Rules
- A "success" notification must contain a green checkmark icon
- Page title must contain "Dashboard" after login
```

---

## Browser Auth State Management

For testing pages behind authentication, save the login state once and reuse it across tasks.

### Save State

```bash
argus auth save --url "https://example.com/login"
```

This opens a headed browser. Log in manually, then press Enter in the terminal. The state (cookies, localStorage, sessionStorage) is saved to `config/browser-states/<name>.json`.

### List Saved States

```bash
argus auth list
```

### Reuse State

```bash
argus run --auth-state example.com \
  --goal "Check profile page loads correctly" \
  --url "https://example.com/profile"
```

The `--auth-state` parameter accepts either a state name (looked up in `config/browser-states/`) or a direct JSON file path.

> Auth states contain session credentials. They are gitignored but should still be treated as sensitive — do not share debug bundles containing them.

---

## Reports & Execution

### Execution Flow

1. **Planner** (LLM) receives the goal and page snapshot, decides the next browser action
2. **Executor** runs the action via Playwright, captures a screenshot and DOM snapshot
3. **Evaluator** (LLM) judges whether the goal is achieved
4. If not satisfied, loop back to step 1 with updated context
5. On action failure, recovery logic re-observes the page and re-plans (up to 2 retries)
6. When done (success or exhaustion), generate HTML + JSON reports

### Report Output

```
outputs/reports/<task_id>/
├── index.html      # Human-readable HTML report
└── report.json     # Structured JSON report
```

**HTML Report Features:**
- Task summary, execution steps, step parameters, screenshots, issues, and errors
- Failed steps are highlighted
- Step parameters and screenshots are collapsible
- Screenshots can be clicked to enlarge
- Screenshots referenced via relative paths where possible

**JSON Report** contains the same data in a machine-readable format, suitable for downstream tools or APIs.

### Report API

```
GET /argus/api/tasks/{task_id}/report    → HTML (default) or JSON (?format=json)
```

### Screenshots

Each execution step captures a screenshot by default. Stored at:

```
outputs/screenshots/<task_id>/
```

Disable with `--no-screenshot`. When disabled, the Planner can still emit `screenshot` actions, but they are logged as skipped without saving an image.

---

## Task Observability

Argus provides rich observability into task execution.

### Execution Timeline

Every task lifecycle event is recorded in SQLite's `task_events` table:
- Task created, queued, started, completed
- Each Planner/Executor/Evaluator cycle
- Browser actions and their results
- Report generation

Get via API:

```
GET /argus/api/tasks/{task_id}/events
```

Or view in the Web Console's **Execution Timeline** tab (real-time via WebSocket).

### LLM Call Traces

Every LLM invocation (Planner and Evaluator) is recorded with full context:

- Phase, event type, model, host, duration, token usage
- Full System Prompt
- Input Payload (the API request body)
- Raw Response (the API response body)
- Parsed Result (after JSON extraction)
- Errors and parse failures

Stored as JSONL:

```
outputs/traces/<task_id>.jsonl
```

Get via API:

```
GET /argus/api/tasks/{task_id}/llm-traces          → list of trace summaries
GET /argus/api/tasks/{task_id}/llm-traces/{trace_id} → single trace detail
```

### Debug Bundle

Download a ZIP with everything needed for offline analysis:

```
GET /argus/api/tasks/{task_id}/debug-bundle
```

Contains:
- `task.json` — full task data
- `traces/llm.jsonl` — all LLM call traces
- `traces/events.jsonl` — all timeline events
- Task screenshots

### Sensitive Data Redaction

All logs, traces, and debug bundles go through recursive key-based redaction:
- Fields matching `api_key`, `apikey`, `authorization`, `cookie`, `password`, `secret`, `token` → value replaced with `***`
- URL query parameters with sensitive names are also redacted
- LLM trace content also uses regex-based redaction for inline secrets (`sk-...`, JWT, inline `key=value`)
- Token usage statistics (`token_usage`) are whitelisted and never redacted

The redaction is field-name-based and does not scan plain text content.

---

## Best Practices

### Writing Test Goals

- **Be specific:** "Test the login form with empty fields and wrong password" is better than "Test the login"
- **Describe expected outcomes:** "Verify the success message appears after form submission"
- **One goal at a time:** Keep each task focused on a single feature or flow
- **Include edge cases:** For forms, mention validation, required fields, error states

### Choosing Between CLI and Web Console

| Situation | Recommended |
|-----------|-------------|
| Quick one-off test | CLI `argus run` |
| Frequent regression checks | CLI with saved auth state |
| Managing many projects | Web Console |
| Investigating failures | Web Console (timeline + LLM debug) |
| Team collaboration | Web Console + shared model configs |

### Optimizing LLM Cost

- Reuse auth states to avoid repeated login steps
- Set appropriate `--max-steps` and `--timeout` for simple tasks
- Use `--create-only` for task templates, execute only when needed
- review LLM traces in the Web Console to identify unnecessary calls

### Security

- Never commit `config/browser-states/`
- Treat debug bundles as potentially sensitive (they contain page content and LLM inputs)
- In production deployment, enable API token auth and rate limiting
- Configure SSRF protection for private network LLM endpoints

---

## Troubleshooting

### LLM Connection Issues

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| `argus llm check` times out | Wrong API endpoint or network issue | Run `argus config llm` to verify settings |
| "401 Unauthorized" | Invalid API key | Run `argus config llm` to re-enter key |
| "Model not found" | Wrong model name | Check provider documentation for correct model ID |
| "SSRF blocked" | Private host not whitelisted | Add host to `config/server.yaml` → `llm.allow_private_hosts` |

### Browser Issues

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| "Browser not found" | Playwright browsers not installed | Run `playwright install chromium` |
| Screenshots are blank | Page not fully loaded or requires auth | Check URL accessibility, use `--headed` to debug |
| Selector not found | DOM changed or wrong selector | Run `argus browser check` to inspect the page |
| Headless mode fails | Missing system dependencies | Use `--headed` or install system libs for Playwright |

### Task Execution

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| Task keeps retrying | Persistent action failure | Check LLM debug tab for Planner decisions |
| Task completes but goal not met | Evaluator misjudgment | Add evaluator prompt extension with specific criteria |
| Report missing screenshots | `--no-screenshot` was used | Re-run without this flag |
| WebSocket disconnects | Server restart or subscriber limit | Check server logs, adjust `events.max_subscribers` |
