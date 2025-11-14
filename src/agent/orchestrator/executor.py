from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.agent.orchestrator.browser_runner import BrowserRunner
from src.agent.orchestrator.context import ContextWindow
from src.agent.orchestrator.llm import LLMClient, LLMError
from src.agent.orchestrator.safety import SafetyDecision, SafetySentinel
from src.config import AppSettings, get_settings
from src.tasking.manager import TaskContext, TaskExecutor

logger = logging.getLogger(__name__)


class AutonomousTaskExecutor(TaskExecutor):
    """TaskExecutor orchestrating planner / navigator / researcher around the LLM."""

    def __init__(
        self,
        settings: Optional[AppSettings] = None,
        llm_client: Optional[LLMClient] = None,
        safety: Optional[SafetySentinel] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm_client or LLMClient(self.settings)
        self.safety = safety or SafetySentinel()
        self.browser_runner = BrowserRunner(self.settings)
        self._active_task_id: Optional[str] = None

    async def execute(self, ctx: TaskContext) -> None:
        instruction = ctx.task.instructions.strip()
        self._active_task_id = ctx.task.task_id
        metadata = ctx.task.metadata or {}
        context_window = ContextWindow(max_items=10)
        context_window.add(f"User task: {instruction}", channel=metadata.get("channel"))

        await ctx.log("Received a new task. Initializing planner pipeline...")

        safety_result = self.safety.inspect(instruction)
        if safety_result.decision == SafetyDecision.REQUIRE_CONFIRMATION:
            prompt = (
                f"This task may lead to dangerous actions ({safety_result.reason})."
                " Confirm we can proceed (reply 'yes' to continue)."
            )
            user_answer = await ctx.request_user_input(prompt)
            if user_answer.strip().lower() not in {"yes", "y"}:
                await ctx.fail("User declined to approve the potentially dangerous task.")
                return
            await ctx.log("User explicitly approved continuing with the risky operation.")

        try:
            self._ensure_not_cancelled(ctx)
            plan = await self._generate_plan(instruction, context_window)
            await ctx.log(f"Planner:\n{plan}")
            context_window.add(plan, stage="planner")

            self._ensure_not_cancelled(ctx)
            navigator_notes = await self._navigator_think(instruction, plan, context_window)
            await ctx.log(f"Navigator notes:\n{navigator_notes}")
            context_window.add(navigator_notes, stage="navigator")

            self._ensure_not_cancelled(ctx)
            browser_report = await self.browser_runner.run(instruction, ctx)
            await ctx.log(f"Browser report:\n{browser_report}")
            context_window.add(browser_report, stage="browser")

            self._ensure_not_cancelled(ctx)
            summary = await self._summarize(plan, navigator_notes, browser_report, context_window)
            summary = self._humanize_summary(summary)
            await ctx.complete(summary)

        except asyncio.CancelledError:
            raise
        except LLMError as exc:
            await ctx.fail(f"LLM error: {exc}")
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.exception("Orchestrator failure")
            await ctx.fail(str(exc))
        finally:
            self._active_task_id = None

    async def _generate_plan(self, instruction: str, context_window: ContextWindow) -> str:
        system_prompt = (
            "You are the planner sub-agent for an autonomous browser assistant."
            " Produce a concise 4-6 step plan focused on concrete browser actions"
            " (which pages to open, what to inspect, what decision to make)."
        )
        user_prompt = f"Task: {instruction}\nContext:\n{context_window.as_prompt()}"
        response = await self.llm.achat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.text.strip()

    async def _navigator_think(
        self,
        instruction: str,
        plan: str,
        context_window: ContextWindow,
    ) -> str:
        system_prompt = (
            "You are the navigator. Imagine you control the real browser: "
            "describe steps, verifications, and possible branches."
        )
        user_prompt = (
            "Use the data below to reason about the agent plan.\n"
            f"Task: {instruction}\n"
            f"Plan:\n{plan}\n"
            f"Context:\n{context_window.as_prompt()}"
        )

        response = await self.llm.achat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.35,
        )
        return response.text.strip()

    async def _summarize(
        self,
        plan: str,
        navigator_notes: str,
        browser_report: str,
        context_window: ContextWindow,
    ) -> str:
        system_prompt = (
            "You are the researcher. Prepare a concise report about progress, risks "
            "and recommended next steps."
        )
        user_prompt = (
            "Summarize the insights from the information below.\n"
            f"Plan:\n{plan}\n"
            f"Navigator:\n{navigator_notes}\n"
            f"Browser:\n{browser_report}\n"
            f"Context:\n{context_window.as_prompt()}"
        )
        response = await self.llm.achat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        return response.text.strip()

    @staticmethod
    def _humanize_summary(summary: str) -> str:
        lowered = summary.lower()
        failure_markers = [
            "no results",
            "could not",
            "need to try",
            "didn't find",
            "failed",
            "not available",
        ]
        if any(marker in lowered for marker in failure_markers):
            return (
                "Я старался выполнить задачу, но результат оказался пустым: "
                f"{summary} Попробуем поискать это в другом месте или уточним запрос?"
            )
        return summary

    async def cancel(self, task_id: str) -> None:
        if self._active_task_id == task_id:
            self.browser_runner.stop_active_agent()
            await self.browser_runner.shutdown()

    def _ensure_not_cancelled(self, ctx: TaskContext) -> None:
        if ctx.is_cancelled():
            raise asyncio.CancelledError
