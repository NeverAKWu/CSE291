"""LLM clients: an OpenAI-compatible client (UCSD TritonAI endpoint) and a
deterministic mock used for development and pipeline tests."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency: float
    model: str


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
    def __init__(self, model: str, temperature: float = 0.0, max_retries: int = 4, timeout: float = 90):
        from openai import OpenAI

        load_dotenv()
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                             base_url=os.environ.get("OPENAI_BASE_URL"), timeout=timeout)

    def complete(self, system: str, user: str) -> LLMResult:
        for attempt in range(self.max_retries):
            try:
                t0 = time.perf_counter()
                r = self.client.chat.completions.create(
                    model=self.model, temperature=self.temperature,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                usage = r.usage
                return LLMResult(
                    text=r.choices[0].message.content or "",
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    latency=time.perf_counter() - t0, model=self.model,
                )
            except Exception:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
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


def make_llm(model: str, mock: bool):
    if mock:
        from .mock_llm import MockLLM
        return MockLLM()
    return OpenAILLM(model)
