"""LLM clients: an OpenAI-compatible client (UCSD TritonAI endpoint) and a
deterministic mock used for development and pipeline tests."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency: float
    model: str
    messages: list[dict] = field(default_factory=list)
    request_params: dict = field(default_factory=dict)
    returned_model: str | None = None
    system_fingerprint: str | None = None
    finish_reason: str | None = None
    attempts: list[dict] = field(default_factory=list)
    usage_known: bool = True
    usage_source: str = "native"
    prompt_tokens_known: bool = True
    completion_tokens_known: bool = True


class LLMCallError(RuntimeError):
    """A failed logical call, with safe audit data for its recorded attempts."""
    def __init__(self, result: LLMResult):
        super().__init__("model call failed; see recorded attempt types/status codes")
        self.result = result


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (avoids an extra dependency). Never commit .env."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class OpenAILLM:
    def __init__(self, model: str, temperature: float = 0.0, max_retries: int = 4,
                 timeout: float = 90, max_tokens: int = 2048):
        from openai import OpenAI

        load_dotenv()
        if max_retries < 1:
            raise ValueError("max_retries counts attempts and must be positive")
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        # One visible retry loop; SDK retries would otherwise hide requests/cost.
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                             base_url=os.environ.get("OPENAI_BASE_URL"), timeout=timeout,
                             max_retries=0)

    def complete(self, system: str, user: str) -> LLMResult:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        params = {"model": self.model, "temperature": self.temperature, "max_tokens": self.max_tokens}
        attempts = []
        started = time.perf_counter()
        for attempt in range(self.max_retries):
            t0 = time.perf_counter()
            try:
                r = self.client.chat.completions.create(**params, messages=messages)
            except Exception as exc:
                delay = 2 ** attempt if attempt < self.max_retries - 1 else 0
                # Exception strings may contain URLs/headers: only safe metadata is logged.
                attempts.append({"attempt": attempt + 1, "status": "error",
                                 "error_type": type(exc).__name__,
                                 "status_code": getattr(exc, "status_code", None),
                                 "latency_s": round(time.perf_counter() - t0, 6),
                                 "backoff_s": delay, "usage_known": False})
                if delay:
                    time.sleep(delay)
                    continue
                raise LLMCallError(LLMResult(
                    "", 0, 0, time.perf_counter() - started, self.model,
                    messages=messages, request_params=params, attempts=attempts,
                    usage_known=False, usage_source="unavailable",
                    prompt_tokens_known=False, completion_tokens_known=False)) from exc
            usage = getattr(r, "usage", None)
            def token_count(name):
                value = getattr(usage, name, None)
                return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
            prompt_value, completion_value = token_count("prompt_tokens"), token_count("completion_tokens")
            prompt_known, completion_known = prompt_value is not None, completion_value is not None
            known = prompt_known and completion_known
            # Preserve available native counters as a lower bound, never invent missing usage.
            prompt, completion = prompt_value if prompt_known else 0, completion_value if completion_known else 0
            usage_source = "native" if known else "partial_native" if prompt_known or completion_known else "unavailable"
            attempts.append({"attempt": attempt + 1, "status": "success",
                             "latency_s": round(time.perf_counter() - t0, 6), "backoff_s": 0,
                             "usage_known": known, "prompt_tokens": prompt,
                             "completion_tokens": completion,
                             "prompt_tokens_known": prompt_known,
                             "completion_tokens_known": completion_known})
            choice = r.choices[0]
            return LLMResult(
                text=choice.message.content or "", prompt_tokens=prompt,
                completion_tokens=completion, latency=time.perf_counter() - started,
                model=self.model, messages=messages, request_params=params,
                returned_model=getattr(r, "model", None),
                system_fingerprint=getattr(r, "system_fingerprint", None),
                finish_reason=getattr(choice, "finish_reason", None), attempts=attempts,
                usage_known=known, usage_source=usage_source,
                prompt_tokens_known=prompt_known, completion_tokens_known=completion_known)
        raise RuntimeError("unreachable")


def extract_json(text: str):
    """Parse the first JSON object in a model response (tolerates code fences / prose)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def make_llm(model: str, mock: bool, **kwargs):
    if mock:
        from .mock_llm import MockLLM
        return MockLLM()
    return OpenAILLM(model, **kwargs)
