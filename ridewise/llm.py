"""OpenAI-compatible LLM client (NeoStats-hosted gpt-oss).

JSON-mode helper with retries and rate-limit back-off. Callers that need to
distinguish an outage from a bad answer catch LLMUnavailable.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .config import settings


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    """The model could not be reached / returned no usable content."""


_JSON_RE = re.compile(r"\{.*\}", re.S)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # strip code fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = _JSON_RE.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    raise LLMUnavailable("model did not return valid JSON")


def _repair_json(obj: dict[str, Any]) -> dict[str, Any]:
    """Drop the spurious 'final{' harmony-channel key gpt-oss sometimes leaks."""
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if "{" not in str(k)}
    return obj


class LLMClient:
    def __init__(self) -> None:
        self._client = None

    @property
    def configured(self) -> bool:
        return settings.llm_configured()

    def _get(self):
        if self._client is None:
            from openai import OpenAI
            from . import tracing
            client = OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                timeout=settings.llm_timeout_s,
            )
            self._client = tracing.wrap_openai(client)  # no-op unless tracing on
        return self._client

    def _create(self, messages, json_mode: bool, max_retries: int = 3):
        client = self._get()
        kwargs: dict[str, Any] = {"model": settings.llm_model, "messages": messages}
        extra_body = {}
        if settings.llm_reasoning_effort:
            extra_body["reasoning_effort"] = settings.llm_reasoning_effort
        if extra_body:
            kwargs["extra_body"] = extra_body
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_err = None
        for attempt in range(max_retries):
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                last_err = e
                # drop json_mode if the endpoint rejects response_format
                if json_mode and "response_format" in msg:
                    kwargs.pop("response_format", None)
                    continue
                if "429" in msg or "rate" in msg.lower():
                    time.sleep(min(2 ** attempt, 8))
                    continue
                if attempt == max_retries - 1:
                    break
                time.sleep(1.0)
        raise LLMUnavailable(f"LLM request failed: {last_err}")

    def chat_json(self, system: str, user: str) -> dict[str, Any]:
        if not self.configured:
            raise LLMUnavailable("LLM is not configured")
        # NOTE: gpt-oss on this endpoint corrupts output under response_format
        # json_object (leaks a "final{" harmony-channel key). It returns clean
        # JSON without it, so we rely on the instruction + robust extraction.
        system = system + "\n\nOutput ONLY a single compact JSON object, no prose, no code fences."
        resp = self._create(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            json_mode=False)
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise LLMUnavailable("empty LLM response")
        return _repair_json(_extract_json(content))

    def chat_text(self, system: str, user: str) -> str:
        if not self.configured:
            raise LLMUnavailable("LLM is not configured")
        resp = self._create(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            json_mode=False)
        return (resp.choices[0].message.content or "").strip()


_default: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default
