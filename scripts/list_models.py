"""List the model ids available at OPENAI_BASE_URL and smoke-test one.

  python scripts/list_models.py              # list models
  python scripts/list_models.py <model-id>   # also send one test request
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpr.llm import OpenAILLM, load_dotenv  # noqa: E402


def main():
    load_dotenv()
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ.get("OPENAI_BASE_URL"))
    for m in client.models.list().data:
        print(m.id)
    if len(sys.argv) > 1:
        r = OpenAILLM(sys.argv[1]).complete("Reply with a JSON object.", 'Return {"ok": true}.')
        print(f"\n{sys.argv[1]}: {r.text!r} ({r.prompt_tokens}+{r.completion_tokens} tokens, {r.latency:.2f}s)")


if __name__ == "__main__":
    main()
