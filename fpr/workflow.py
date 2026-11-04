"""Versioned researcher -> planner -> executor workflow and verification gates."""
from __future__ import annotations

import json
import time

from . import agents
from .env import TOOL_SPECS, Sandbox
from .faults import Injector
from .llm import LLMCallError
from .trace import Tracer

MAX_EXEC_STEPS = 8
PROTOCOL_VERSION = "fpr-v2"


def run_workflow(task, llm, tracer: Tracer, sandbox: Sandbox, injector: Injector | None = None,
                 verify: bool = False, prefix: str = "", verification_scope: str = "rpe",
                 max_verification_retries: int = 1) -> dict:
    """Gate candidates before use; every regenerated candidate is verified again.

    `rp` checks researcher/planner; `rpe` also checks each executor action before
    mutation. Both are v2: legacy saved experiments used an unverified retry.
    """
    if verification_scope not in ("rp", "rpe") or max_verification_retries < 0:
        raise ValueError("invalid verification settings")
    inj = injector or Injector(None, task)
    req = task.request()
    t0 = time.perf_counter()
    n0 = len(tracer.artifacts)
    stats = {"verify_calls": 0, "verify_rejections": 0, "verification_halted": False}

    def finish():
        sim = sum(a.meta.get("sim_latency", 0.0) for a in tracer.artifacts[n0:])
        wall = time.perf_counter() - t0
        stats.update(wall_latency_s=round(wall, 6), simulated_latency_s=round(sim, 6),
                     latency_s=round(wall, 6), effective_latency_s=round(wall + sim, 6))
        return stats

    def invoke(name, call, key, inputs, kind="llm_output"):
        try:
            out, res = call()
        except LLMCallError as exc:
            tracer.add("llm_error", name, {"error": "model_call_failed"}, key=key,
                       inputs=inputs, llm=exc.result)
            raise
        oid = tracer.add(kind, name, out, key=key, inputs=inputs, llm=res)
        return out, oid

    tid = tracer.add("task", "user", {"instruction": task.instruction, "request": req}, key=prefix + "task")
    # Represent every initial writer, including missing-file fallback, in the graph.
    init = [p for p, w in sandbox.writers.items() if w == "init"]
    if init:
        sid = tracer.add("state", "env", {p: sandbox.files[p] for p in init}, key=prefix + "state:init")
        sandbox.writers.update({p: sid for p in init})
    # Sandbox uses a sentinel for reads of paths that do not yet exist.
    missing_state_id = tracer.add("state", "env", {}, key=prefix + "state:missing")
    inj.apply_state(sandbox, tracer)

    budgets_text, budgets_writer = sandbox.read("budgets.json")
    retrieval = {"team": task.team, "vendor_records": [dict(r) for r in task.catalog_records],
                 "manager_email": task.manager_email,
                 "budget_remaining": json.loads(budgets_text)[task.team]}
    rid = tracer.add("retrieval", "kb", retrieval, key=prefix + "retrieval", inputs=[tid, budgets_writer])
    retrieval, rid = inj.at("retrieval", retrieval, rid, tracer)

    def stage(name, call, inputs, sources, key=None, inject=True):
        key = key or prefix + name
        previous_rejection = []
        for attempt in range(max_verification_retries + 1 if verify else 1):
            suffix = "" if attempt == 0 else f":retry{attempt}"
            out, oid = invoke(name, call, key + suffix, inputs + previous_rejection)
            if inject:
                out, oid = inj.at(name, out, oid, tracer)
            needs_check = verify and (name != "executor" or verification_scope == "rpe")
            if not needs_check:
                return out, oid
            v, vid = invoke("verifier", lambda: agents.verify(
                llm, name, task.instruction, sources(), out),
                f"{prefix}verify:{name}{key[len(prefix + name):]}{suffix}", [oid], "verify")
            stats["verify_calls"] += 1
            # Malformed/missing verdicts never count as approval.
            if v.get("ok") is True:
                return out, oid
            stats["verify_rejections"] += 1
            previous_rejection = [vid]
        stats["verification_halted"] = True
        tracer.add("halt", "harness", {"stage": name, "reason": "verification_retry_limit"},
                   key=key + ":halt", inputs=previous_rejection)
        return None, None

    facts, fid = stage("researcher", lambda: agents.research(llm, task.instruction, req, retrieval),
                       [tid, rid], lambda: {"retrieval": retrieval})
    if facts is None:
        return finish()
    plan, pid = stage("planner", lambda: agents.plan(llm, task.instruction, req, facts),
                      [tid, fid], lambda: {"request": req, "facts": facts})
    if plan is None:
        return finish()

    history: list[dict] = []
    result_ids: list[str] = []
    for step in range(MAX_EXEC_STEPS):
        call, cid = stage("executor", lambda: agents.execute_step(llm, req, plan, history),
                          [pid] + result_ids,
                          lambda: {"request": req, "facts": facts, "plan": plan,
                                   "history": history, "retrieval": retrieval},
                          key=f"{prefix}executor#{step}", inject=False)
        if call is None or call.get("tool") in (None, "done") or "error" in call:
            break
        before_files = dict(sandbox.files)
        ext_before = len(sandbox.external)
        result, reads, writes = sandbox.execute(call)
        reads = [missing_state_id if r == "init" else r for r in reads]
        # Deletion consumes the prior file version even though Sandbox only marks a write.
        for path in writes:
            if path in sandbox.writers and sandbox.writers[path] not in reads:
                reads.append(sandbox.writers[path])
        spec = TOOL_SPECS.get(call["tool"], {})
        changed = {p: {"before": before_files.get(p), "after": sandbox.files.get(p)}
                   for p in before_files.keys() | sandbox.files.keys()
                   if before_files.get(p) != sandbox.files.get(p)}
        xid = tracer.add("tool_result", f"tool:{call['tool']}", {"call": call, "result": result},
                         key=f"{prefix}tool#{step}", inputs=[cid] + reads,
                         external=spec.get("external", False), reversible=spec.get("reversible", True),
                         read_artifact_ids=reads, write_paths=writes, state_diff=changed,
                         external_added=sandbox.external[ext_before:])
        for p in writes:
            sandbox.writers[p] = xid
        if call["tool"] == "place_order":
            result, xid = inj.at("tool_result", result, xid, tracer)
        history.append({"call": call, "result": result})
        result_ids.append(xid)
    return finish()
