from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import AppSettings, get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    raw: Dict[str, Any]


class LLMClient:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or get_settings()
        base_url = self.settings.llm_base_url.rstrip("/")
        if not base_url.endswith("/chat/completions") and not base_url.endswith("/completions"):
            base_url = f"{base_url}/chat/completions"
        self.base_url = base_url
        self.model = self.settings.llm_model_id
        self.headers = {
            "Content-Type": "application/json",
            **self.settings.llm_headers(),
        }
        if not self.settings.openrouter_api_key and "Authorization" not in self.headers:
            logger.warning("LLM client started without an API key; requests will fail.")

    async def achat(self, messages: List[Dict[str, Any]], **extra: Any) -> LLMResponse:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            **extra,
        }
        payload.setdefault("max_output_tokens", self.settings.context_max_tokens)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.settings.llm_max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(LLMError),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=self.settings.llm_request_timeout) as client:
                    response = await client.post(
                        self.base_url,
                        headers=self.headers,
                        content=json.dumps(payload),
                    )
                if response.status_code >= 400:
                    logger.error("LLM error %s: %s", response.status_code, response.text)
                    raise LLMError(f"LLM error: {response.status_code} {response.text}")

                data = response.json()
                text = self._extract_text(data)
                if text is None:
                    raise LLMError("LLM response did not contain text")
                return LLMResponse(text=text, raw=data)

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> Optional[str]:
        choices = data.get("choices")
        if not choices:
            return None
        message = choices[0].get("message")
        if not message:
            return None
        content = message.get("content")
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            return "\n".join(filter(None, text_parts))
        if isinstance(content, str):
            return content
        return message.get("text")
