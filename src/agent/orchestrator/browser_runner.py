from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.browser.browser import BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserState
from langchain_core.language_models.chat_models import BaseChatModel

from src.agent.browser_use.browser_use_agent import BrowserUseAgent
from src.browser.custom_browser import CustomBrowser
from src.controller.custom_controller import CustomController
from src.config import AppSettings, get_settings
from src.tasking.manager import TaskContext
from src.utils import llm_provider

logger = logging.getLogger(__name__)


class BrowserRunner:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.browser: Optional[CustomBrowser] = None
        self.browser_context: Optional[BrowserContext] = None
        self.controller: Optional[CustomController] = None
        self.llm: Optional[BaseChatModel] = None
        self._mcp_config: Optional[Dict[str, Any]] = None
        if self.settings.mcp_server_config:
            try:
                self._mcp_config = json.loads(self.settings.mcp_server_config)
            except json.JSONDecodeError:
                logger.warning("Failed to parse MCP config from MCP_SERVER_CONFIG.")

    async def ensure_ready(self, ctx: TaskContext) -> None:
        if self.browser is None:
            await self._create_browser()
        if self.controller is None:
            await self._create_controller(ctx)
        else:
            self.controller.ask_assistant_callback = self._build_assistant_callback(ctx)
        if self.llm is None:
            self.llm = self._create_llm()
        if not self.browser_context or not self.settings.keep_browser_open:
            await self._create_context()

    async def _create_browser(self) -> None:
        extra_args = list(getattr(self.settings, "extra_browser_args", []))
        if self.settings.browser_user_data:
            extra_args.append(f"--user-data-dir={self.settings.browser_user_data}")
        cdp_url: Optional[str] = None
        if self.settings.browser_cdp:
            cdp_url = self.settings.browser_cdp
        elif self.settings.use_own_browser:
            host = self.settings.browser_debugging_host or "127.0.0.1"
            cdp_url = f"http://{host}:{self.settings.browser_debugging_port}"
        browser_config = BrowserConfig(
            headless=self.settings.playwright_headless,
            browser_binary_path=None if cdp_url else (self.settings.browser_path or None),
            extra_browser_args=extra_args,
            cdp_url=cdp_url,
            chrome_remote_debugging_port=self.settings.browser_debugging_port,
            new_context_config=BrowserContextConfig(
                window_width=self.settings.resolution_width,
                window_height=self.settings.resolution_height,
            ),
        )
        self.browser = CustomBrowser(config=browser_config)

    async def _create_context(self) -> None:
        if not self.browser:
            raise RuntimeError("Browser is not initialized")
        downloads = self.settings.runs_path / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        recordings = self.settings.runs_path / "recordings"
        recordings.mkdir(parents=True, exist_ok=True)
        context_config = BrowserContextConfig(
            window_width=self.settings.resolution_width,
            window_height=self.settings.resolution_height,
            save_downloads_path=str(downloads),
            save_recording_path=str(recordings),
            force_new_context=not self.settings.keep_browser_open,
        )
        self.browser_context = await self.browser.new_context(config=context_config)

    async def _create_controller(self, ctx: TaskContext) -> None:
        self.controller = CustomController(ask_assistant_callback=self._build_assistant_callback(ctx))
        if self._mcp_config:
            await self.controller.setup_mcp_client(self._mcp_config)

    def _create_llm(self) -> BaseChatModel:
        return llm_provider.get_llm_model(
            provider=self.settings.agent_llm_provider,
            model_name=self.settings.agent_llm_model,
            temperature=self.settings.agent_llm_temperature,
            base_url=self.settings.llm_base_url,
            api_key=self.settings.openrouter_api_key,
            http_referer=self.settings.llm_http_referer,
            title=self.settings.llm_title,
        )

    def _build_assistant_callback(self, ctx: TaskContext):
        async def ask_user(query: str, browser: BrowserContext):
            response = await ctx.request_user_input(query)
            return {"response": response}

        return ask_user

    async def run(self, instruction: str, ctx: TaskContext) -> str:
        await self.ensure_ready(ctx)
        assert self.browser and self.browser_context and self.controller and self.llm

        history_path = self._build_history_dir()
        gif_path = history_path / "agent.gif"

        async def step_cb(state: BrowserState, output: AgentOutput, step_num: int):
            url = getattr(state, "url", "")
            title = getattr(state, "title", "")
            await ctx.log(
                f"Step {step_num}: {title or url}",
                metadata={"url": url, "title": title},
            )

        def done_cb(history: AgentHistoryList):
            logger.info("BrowserUseAgent finished running. History length: %s", len(history.history))

        agent = BrowserUseAgent(
            task=instruction,
            llm=self.llm,
            browser=self.browser,
            browser_context=self.browser_context,
            controller=self.controller,
            register_new_step_callback=step_cb,
            register_done_callback=done_cb,
            source="task-runner",
        )
        agent.settings.generate_gif = str(gif_path)
        agent.settings.max_actions_per_step = 10
        history = await agent.run(max_steps=self.settings.max_agent_steps)
        result = history.final_result()
        result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

        errors = getattr(history, "errors", None)
        if callable(errors):
            errs = errors()
            if errs:
                await ctx.log(f"Warnings reported by BrowserUseAgent: {errs}", level="warning")

        if not self.settings.keep_browser_open and self.browser_context:
            await self.browser_context.close()
            self.browser_context = None

        return result_str

    def _build_history_dir(self) -> Path:
        run_dir = self.settings.runs_path / datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    async def shutdown(self) -> None:
        if self.browser_context:
            await self.browser_context.close()
            self.browser_context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.controller:
            await self.controller.close_mcp_client()
            self.controller = None
