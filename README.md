# Autonomous Browser Agent WebUI

> Refactored fork of `browser-use/web-ui` aimed at running a fully autonomous agent that drives a visible browser, reasons over multi-step tasks, and integrates OpenRouter (Gemini 2.5 Flash Lite) out of the box.

## Why this refactor
- **True autonomy** – Users submit any natural-language goal (spam cleanup, food ordering, job hunting, etc.) and the agent runs end-to-end until it needs clarification.
- **Visible browser + persistent sessions** – Operates in non-headless Playwright contexts or connects to an existing Chrome profile (`BROWSER_PATH` + `BROWSER_USER_DATA`), so you log in once and keep cookies.
- **No brittle scripts** – The agent inspects live DOM state, assigns indices on the fly, and decides which elements to interact with without hardcoded selectors or task templates.
- **Advanced patterns** – Built-in sub-agents (Planner, Navigator, Researcher, Safety Sentinel), automatic error recovery, and a security layer that asks before destructive actions.
- **Token-aware context management** – DOM distillation, screenshot captioning, and rolling memory summaries keep LLM prompts compact while preserving situational awareness.

## High-level architecture
1. **Interaction Layer** – Gradio WebUI + CLI entry point to submit tasks, stream reasoning logs, and feed clarifications back to the agent.
2. **Task Orchestrator** – Multi-agent brain coordinating Planner ↔ Navigator ↔ Researcher; manages memory, retries, and OpenRouter model calls.
3. **Browser Control Layer** – Playwright-based `CustomBrowser`/`CustomController` that exposes strongly typed actions (click, input, file upload, etc.) without pre-labeled selectors.
4. **Context Fabric** – DOM sampler, screenshot captioner, and event memory buffer used by the LLM instead of dumping entire pages.
5. **Safety & Oversight** – Security gate that halts high-risk actions (delete, checkout, transfer) until the user approves; watchdog automatically restarts the browser context on crashes.
6. **Observability** – Every run writes structured traces, screenshots, and optional GIFs to `./runs/<timestamp>` for debugging and demo purposes.

See `docs/IMPLEMENTATION_PLAN.md` for the detailed roadmap and to-do list.

## Requirements
- Python 3.11+
- [Playwright](https://playwright.dev/python/) with Chromium installed (`playwright install chromium --with-deps`)
- Chrome / Edge (for persistent sessions) or Chromium bundled by Playwright
- Valid OpenRouter API key (Gemini 2.5 Flash Lite by default, but OpenAI/Anthropic keys work via the same interface)

## Installation

```bash
git clone https://github.com/browser-use/web-ui.git
cd web-ui
python -m venv .venv
.\.venv\Scripts\activate      # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
playwright install chromium --with-deps
cp .env.example .env
```

### Configure `.env`

```env
# === LLM / OpenRouter ===
OPENROUTER_API_KEY=sk-...
LLM_MODEL_ID=google/gemini-2.5-flash-lite
LLM_BASE_URL=https://openrouter.ai/api/v1/chat/completions
LLM_HTTP_REFERER=https://yourdomain.example
LLM_TITLE=Autonomous Browser Agent

# === Browser / Playwright ===
BROWSER_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
BROWSER_USER_DATA="C:\Users\<you>\AppData\Local\Google\Chrome\User Data"
PERSIST_BROWSER=true
PLAYWRIGHT_HEADLESS=false

# === Safety & Behavior ===
HUMAN_APPROVAL_REQUIRED=true
MAX_CONSECUTIVE_FAILURES=5
MAX_AGENT_STEPS=120
CONTEXT_MAX_TOKENS=6000
SAVE_RUN_ARTIFACTS=true

# === Optional ===
ENABLE_CLI=true
RUNS_PATH=./runs
```

> Tip: leave `BROWSER_USER_DATA` empty to let Playwright manage an isolated profile. When pointing to your own Chrome profile, close all running Chrome windows first.

## Running the agent

### WebUI (default)
```bash
python webui.py --ip 127.0.0.1 --port 7788 --theme Ocean
```
- Navigate to `http://127.0.0.1:7788`.
- Submit a task (e.g., “Прочитай последние 10 писем в Яндекс.Почте и удали спам”).
- Watch the step log update in real time while the browser performs actions you can see.
- When the agent requests approval (e.g., deleting emails, confirming orders), respond via the dialog.

### Terminal / CLI
```bash
python -m src.cli "Найди 3 подходящие вакансии AI-инженера на hh.ru и откликнись"
```
- Streams reasoning + action traces in the terminal.
- Press `Ctrl+C` once to pause (agent waits), press again to terminate the run.

## Workflow & context strategy
1. **Observation** – After each tool call, the controller captures DOM excerpts with numbered nodes, viewport screenshots, and metadata (URL, title, tab list).
2. **Distillation** – A lightweight ranker scores nodes (text density, role hints, recent interactions) and feeds only top matches to the Planner, keeping prompts tight.
3. **Memory** – The Researcher sub-agent continuously summarizes what has been read/done (e.g., list of emails scanned, cart items). Summaries are appended to a rolling history buffer.
4. **Decision** – Planner reasons over the condensed context and emits the next high-level instruction. Navigator translates it into browser actions via tool calling.
5. **Safety** – Before deletion/checkout/etc., Safety Sentinel evaluates the intent. If high risk, the UI prompts the user for confirmation; rejection triggers replanning.
6. **Reporting** – When `history.is_done()` is triggered, the agent validates the output and emits a structured report (counts of spam removed, job postings applied, etc.).

## Advanced behavior built in
- **Sub-agents** – Dedicated Planner/Navigator/Researcher roles keep prompts short and allow specialization.
- **Error recovery** – Categorizes failures (network, DOM drift, auth) and retries with exponential backoff or page refreshes; falls back to asking the user only when strictly necessary.
- **Security layer** – Configurable policy ensures no destructive action happens without opt-in approval; all gated decisions are logged to the run artifacts.
- **Flexible models** – Works with Gemini 2.5 Flash Lite by default via OpenRouter, but `LLM_MODEL_ID` supports any available provider (OpenAI, Anthropic, DeepSeek, etc.). Tool-calling support is auto-detected per model.
- **No hardcoded selectors** – DOM nodes are referenced via generated indices, computed at runtime from the live accessibility tree.

## Development workflow
1. Read `docs/IMPLEMENTATION_PLAN.md` for the current phase, technical notes, and to-do list.
2. Use `requirements-dev.txt` (if present) for linting/testing helpers; otherwise install `ruff`, `pytest`, etc. manually.
3. Run `pytest tests` before submitting changes. For browser automation, prefer mocked fixtures; limit live-site tests to manual QA runs.
4. Keep `runs/` artifacts out of commits by default (already `.gitignore`d).
5. Add brief comments only for non-obvious logic (context rankers, safety gating, etc.).

## Troubleshooting
- **Playwright can’t start the browser** – Make sure Chrome is closed when attaching to your own profile and that `chrome_remote_debugging_port` isn’t occupied.
- **Agent loops on the same page** – Check the step log; you may need to supply extra context (e.g., “Я уже на странице заказов”) or provide human assistance when asked.
- **Token limit warnings** – Tune `CONTEXT_MAX_TOKENS`, reduce screenshot frequency, or temporarily disable the Researcher sub-agent via `.env`.
- **OpenRouter 401 errors** – Ensure `OPENROUTER_API_KEY` is valid and not rate-limited. Set `LLM_HTTP_REFERER` and `LLM_TITLE` if your OpenRouter account enforces them.

## Next steps
- Follow the to-do list inside `docs/IMPLEMENTATION_PLAN.md`.
- Record demo sessions (`runs/latest/agent_history.gif`) to showcase complex tasks (spam deletion, food order, job search).
- Share feedback/issues in repo discussions once the refactor milestones are implemented.
