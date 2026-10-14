"""Thin wrapper around any OpenAI-compatible chat endpoint (OpenRouter, Gemini,
Groq, Ollama...). Adds retries for free-tier rate limits and token accounting."""

from __future__ import annotations

import time

from .config import BACKUP_MODELS, Settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        from openai import OpenAI

        if not settings.api_key:
            raise LLMError("No LLM_API_KEY set. Add it to the .env file (see README).")
        self.settings = settings
        self.model = settings.model
        self.backups = [m for m in BACKUP_MODELS.get(settings.provider, []) if m != settings.model]
        headers = {}
        if settings.provider == "openrouter":
            # optional attribution headers recommended by OpenRouter
            headers = {"HTTP-Referer": "https://github.com/mehak-t/Academic-Policy-Compliance-Agent",
                       "X-Title": "Academic Policy Compliance Agent"}
        elif settings.provider == "gemini":
            # newer Gemini keys are only accepted through Google's own header
            headers = {"x-goog-api-key": settings.api_key}
        self.client = OpenAI(base_url=settings.base_url, api_key=settings.api_key, default_headers=headers, timeout=90,
                             max_retries=0)  # retries + model fallback are handled below
        self.exhausted: set[str] = set()
        self.model_calls: dict[str, int] = {}
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def chat(self, messages: list[dict], max_retries: int = 6, json_mode: bool = True) -> str:
        """Try the main model first on every call; on a busy / empty reply fall through to the
        backup models for this call only. A model whose daily quota is used up is skipped for the rest of the run."""
        last_err = None
        for attempt in range(max_retries):
            for model in [m for m in [self.settings.model, *self.backups] if m not in self.exhausted]:
                use_json = json_mode
                for _ in range(2):  # second try without JSON mode if the first reply was empty
                    try:
                        text = self._call(model, messages, use_json)
                        self.model = model
                        return text
                    except Exception as e:  # noqa: BLE001 - provider SDK errors vary a lot
                        last_err = e
                        msg = str(e).lower()
                        if use_json and ("response_format" in msg or "empty message" in msg or ("json" in msg and "support" in msg)):
                            use_json = False
                            continue
                        if "quota" in msg or "resource_exhausted" in msg or "no longer available" in msg:
                            self.exhausted.add(model)
                        break
            time.sleep(min(10 * (attempt + 1), 30))  # every model busy -> wait and go round again
        raise LLMError(f"LLM call failed after retries: {last_err}")

    def _call(self, model: str, messages: list[dict], json_mode: bool) -> str:
        # thinking models spend part of max_tokens on reasoning, so leave plenty of room
        kwargs = dict(model=model, messages=messages, temperature=self.settings.temperature, max_tokens=16000)
        if self.settings.provider == "gemini":
            kwargs["reasoning_effort"] = "low"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        self.calls += 1
        self.model_calls[model] = self.model_calls.get(model, 0) + 1
        if resp.usage:
            self.prompt_tokens += resp.usage.prompt_tokens or 0
            self.completion_tokens += resp.usage.completion_tokens or 0
        if not resp.choices:
            raise LLMError(f"Empty response: {getattr(resp, 'error', resp)}")
        text = resp.choices[0].message.content or ""
        if not text.strip():
            raise LLMError(f"Model {model} returned an empty message (finish_reason={resp.choices[0].finish_reason})")
        return text

    def usage(self) -> dict:
        return {"model": self.model, "provider": self.settings.provider, "llm_calls": self.calls, "calls_per_model": self.model_calls,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}


class ScriptedLLM:
    """Replays canned responses - used by the unit tests so they run offline."""

    def __init__(self, responses: list[str], model: str = "scripted"):
        self.responses = list(responses)
        self.model = model
        self.calls = 0
        self.seen: list[list[dict]] = []

    def chat(self, messages, **_):
        self.seen.append(messages)
        self.calls += 1
        if not self.responses:
            return '{"thought": "nothing left", "final_answer": "done"}'
        return self.responses.pop(0)

    def usage(self):
        return {"model": self.model, "provider": "scripted", "llm_calls": self.calls, "prompt_tokens": 0, "completion_tokens": 0}
