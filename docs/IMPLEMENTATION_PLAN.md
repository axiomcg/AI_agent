# Refactor Implementation Plan

## Goals & Success Criteria
- Deliver an autonomous agent that can accept open-ended tasks via terminal or WebUI, operate a visible browser, and only pause when human confirmation is strictly required.
- Preserve persistent Playwright sessions so the user can log in once and keep their cookies/profiles between tasks (leveraging `src/browser/custom_browser.py` and Chrome user data dirs).
- Integrate OpenRouter (default: `google/gemini-2.5-flash-lite`) as the main reasoning model with pluggable fallbacks for OpenAI/Claude while respecting API limits.
- Provide strategies for bounded context windows: distilled DOM state, screenshot captions, incremental memory summaries instead of raw page dumps.
- Ship at least one advanced agentic pattern (sub-agents, error recovery, or security gate). Target: multi-agent planner + safety sentinel + autonomous retry policy.
- Remove brittle heuristics: no hard-coded flows, selectors, or task templates.

## Architecture Overview

```
                   ┌──────────────────────┐
                   │  Interaction Layer   │
                   │  (Gradio UI + CLI)   │
                   └────────────┬─────────┘
                                │
                   ┌────────────▼────────────┐
                   │  Task Orchestrator      │
                   │  (Planner + Memory)     │
                   └────────────┬────────────┘
                                │ ToolCalls
                   ┌────────────▼────────────┐
                   │  Browser Control Layer  │
                   │ (Playwright + Controller│
                   └────────────┬────────────┘
                                │
                   ┌────────────▼────────────┐
                   │ Safety & Oversight      │
                   │ (Risk Gate, Recovery)   │
                   └────────────┬────────────┘
                                │
                   ┌────────────▼────────────┐
                   │ Observability Pipeline  │
                   │ (Logs, Artifacts, VNC)  │
                   └─────────────────────────┘
```

### 1. Interaction Layer
- Extend `webui.py` + `src/webui/interface.py` to expose:
  - Task composer (text input, optional clarifications, status feed).
  - Live run viewer (step log + embedded VNC stream).
  - Manual intervention prompt for when the agent requests user help.
- Add CLI entry-point (`python -m src.cli`) for terminal users; both surfaces push jobs to the same orchestrator queue.

### 2. Task Orchestrator
- Core orchestrator class (e.g., `src/agent/orchestrator.py`) that owns:
  - Planner LLM client (`Gemini 2.5 Flash Lite`) using OpenRouter key, pluggable via `.env`.
  - Sub-agents:
    - **Navigator** – decides next browser action.
    - **Researcher** – extracts structured info / builds summaries for reporting.
    - **Safety Sentinel** – intercepts destructive intents and requests confirmation.
  - Memory/context manager that stores:
    - Latest distilled DOM chunks.
    - Step summaries (ActionResult + reasoning).
    - Conversation state with the user.
- Provide tool-calling surfaces that avoid pre-defined selectors by letting LLM inspect DOM snapshots (indexed elements, attributes, visible text).

### 3. Browser Control Layer
- Reuse `CustomBrowser`/`CustomBrowserContext` to guarantee:
  - Visible, non-headless Playwright sessions.
  - `BROWSER_PATH` & `BROWSER_USER_DATA` for persistent profiles.
  - Optional remote debugging port for attaching user’s own browser.
- Augment `CustomController` to emit:
  - Consistent observation schema (accessibility tree snippet, bounding boxes, screenshot crops).
  - Error metadata (timeouts, navigation failures).
- Build a watchdog that restarts the context or reloads pages on fatal Playwright errors without killing the orchestrator.

### 4. Context & Memory Fabric
- DOM Distillation pipeline:
  1. Query DOM via Playwright accessibility tree.
  2. Score elements by visibility + semantic importance (role, aria labels, innerText).
  3. Return top *k* nodes (configurable) with stable indices instead of CSS selectors.
  4. Maintain rolling window (e.g., last 3 DOM snapshots) and allow summarization via LLM.
- Visual capture:
  - Capture viewport screenshot every step; send to model only when textual signal is insufficient (fallback).
  - Generate caption/vision embedding via local captioner to reduce token load.
- Long-term memory:
  - After each step, compress reasoning & results into short bullet summary appended to a task memory buffer.
  - When tokens exceed threshold, trim oldest summaries but keep final outputs.

### 5. Safety, Recovery & Advanced Patterns
- **Security layer**: risk classifier prompts the user whenever the LLM proposes actions containing destructive verbs (delete, checkout, transfer). If approved, the action proceeds; otherwise, planner re-plans.
- **Error-handling policy**:
  - Categorize failures (transient, DOM mismatch, auth) and automatically retry with adjusted strategy (refresh page, re-query DOM, request human input).
  - Limit consecutive failures per spec (configurable).
- **Sub-agent flow**:
  1. Planner decomposes a goal into mini-goals.
  2. Navigator executes browsing steps; Researcher collects data and updates memory.
  3. Safety Sentinel runs in parallel watching tool calls.
- **User intervention hook**:
  - Exposed to UI so agent can ask clarifying questions (already prototyped inside `CustomController.ask_for_assistant`).

### 6. Observability & Reporting
- Structured run log stored in `./runs/<timestamp>` with:
  - `trace.json` (steps, actions, DOM summaries).
  - `screenshots/step-XX.png`.
  - Optional `agent_history.gif`.
- Final report composer delivering:
  - Task status (done/blocked).
  - Key data (e.g., email subjects, order confirmation details).
  - Safety decisions (what destructive intents were blocked or approved).

## Implementation Phases

| Phase | Scope | Key Deliverables |
| --- | --- | --- |
| 0. Foundation | Config, env templates, dependency audit | `.env` to include `OPENROUTER_API_KEY`, `LLM_MODEL_ID`, feature flags for CLI/UI, Telemetry opt-in |
| 1. Interaction Layer | WebUI/CLI tasks, job queue | Unified `TaskManager`, UI forms, streaming logs, bridging to orchestrator |
| 2. Orchestrator & Sub-Agents | Planner, Navigator, Researcher, Memory | `TaskOrchestrator`, `NavigatorAgent`, `ResearchAgent`, `SafetySentinel`, conversation state |
| 3. Browser & Context Engine | DOM sampling, screenshot captions, error recovery | Extended `CustomController`, DOM scorer, screenshot service, watchdog |
| 4. Safety & Security | Risk gate, approvals, sensitive action policies | Approval UI modal, destructive intent classifier, audit log |
| 5. Reporting & QA | Run history, tests, docs | Regression tests (unit + integration), updated README/showcase, CLI smoke script |

## Step-by-Step To-Do List
1. **Repository hygiene** – update `requirements.txt`, pin Playwright/Gradio versions, and refresh `.env.example` with OpenRouter + browser profile variables.
2. **Configuration layer** – add `src/config/settings.py` (Pydantic settings) to unify all environment + feature flags.
3. **LLM client wrapper** – implement OpenRouter client factory supporting Gemini 2.5 Flash Lite plus fallback providers; include retry/backoff + telemetry tags.
4. **Task queue + orchestration skeleton** – create `TaskOrchestrator` with async queue, step loop, and hooks for planner/sub-agents; integrate existing `BrowserUseAgent` state machine.
5. **Sub-agent modules** – add Navigator (browser tool caller), Researcher (info extraction & report builder), Safety Sentinel (intent classifier & approval pipeline).
6. **Context manager** – build DOM distillation, screenshot caption service, and rolling memory buffer; expose them to planner prompts instead of raw HTML.
7. **WebUI refresh** – redesign `src/webui/interface.py` with sections: Task composer, Status board, Event log, Browser session controls, Safety prompts.
8. **CLI interface** – add `src/cli/main.py` to pipe stdin tasks to orchestrator and stream logs for terminal workflows.
9. **Safety approvals** – implement destructive-action detector + UI prompts; persist decisions in audit log and respect them per session.
10. **Error recovery policies** – extend controller/watchdog to categorize and auto-retry; log metrics for debugging.
11. **Reporting module** – compile structured summaries per task (emails read, orders placed, applications sent) and render in UI + CLI.
12. **Testing & validation** – automate synthetic scenarios (read email list, add to cart, search job) using mocked sites; include unit tests for DOM scoring + prompt templates.
13. **Documentation & onboarding** – finalize README (usage, architecture) and add developer guides for extending agents/tools.
14. **Demo assets** – optional screen recordings or GIF generator improvements to showcase end-to-end flows.

## Risks & Mitigations
- **Token exhaustion** – enforce chunking thresholds, fall back to screenshot captioning, and allow configurable `MAX_CONTEXT_TOKENS`.
- **Model/tool mismatch** – automatically select `tool_calling_method` per model (already partially handled in `BrowserUseAgent`); include health check that fails fast when API key missing.
- **Persistent profile conflicts** – detect when Chrome profile is already open and prompt the user via UI; fallback to temporary session to avoid crashes.
- **Security/privacy** – never log sensitive DOM content verbatim; respect `.env` redaction list; double-confirm destructive actions.

This plan, paired with the README rewrite, should give clear guidance for implementing the new autonomous agent requirements.

