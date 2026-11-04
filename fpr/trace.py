"""Provenance trace: every message, intermediate result, tool action and
injected fault becomes an Artifact with explicit `inputs` (dependency edges).

`key` names an artifact's position in the workflow ("researcher",
"executor#2", ...) so the same position can be aligned across a clean run
and a faulty run of the same task.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict


def content_hash(content) -> str:
    return hashlib.sha1(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()[:12]


@dataclass
class Artifact:
    id: str
    key: str
    kind: str  # task | retrieval | llm_output | tool_result | fault | verify | recovery
    producer: str
    content: object
    inputs: list[str]
    hash: str
    t: float
    llm: dict | None = None  # prompt_tokens, completion_tokens, latency
    injected: bool = False
    meta: dict = field(default_factory=dict)


class Tracer:
    def __init__(self, run_id: str, meta: dict | None = None):
        self.run_id = run_id
        self.meta = meta or {}
        self.artifacts: list[Artifact] = []
        self.by_id: dict[str, Artifact] = {}
        self._t0 = time.perf_counter()
        self.tracking_overhead_s = 0.0

    def add(self, kind: str, producer: str, content, *, key: str, inputs=(), llm=None,
            injected: bool = False, **meta) -> str:
        started = time.perf_counter()
        llm_data = None
        if llm is not None:
            llm_data = asdict(llm)
            llm_data["raw_response"] = llm_data.pop("text")
            llm_data["latency"] = round(llm.latency, 6)
        aid = f"a{len(self.artifacts):03d}"
        art = Artifact(
            id=aid, key=key, kind=kind, producer=producer, content=content,
            inputs=[i for i in inputs if i], hash=content_hash(content),
            t=round(time.perf_counter() - self._t0, 4),
            llm=llm_data,
            injected=injected, meta=meta,
        )
        self.artifacts.append(art)
        self.by_id[aid] = art
        self.tracking_overhead_s += time.perf_counter() - started
        return aid

    def descendants(self, roots) -> set[str]:
        roots = set(roots)
        out: set[str] = set()
        for art in self.artifacts:  # artifacts are appended in topological order
            if any(i in roots or i in out for i in art.inputs):
                out.add(art.id)
        return out

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": self.run_id, "meta": self.meta}) + "\n")
            for art in self.artifacts:
                f.write(json.dumps(asdict(art), default=str) + "\n")


def load_trace(path) -> tuple[dict, list[dict]]:
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    return lines[0], lines[1:]
