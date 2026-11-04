"""researcher -> planner -> executor workflow with trace recording, fault
injection hooks at every stage boundary, and an optional always-verify mode."""
from __future__ import annotations

import json
import time

from . import agents
from .env import TOOL_SPECS, Sandbox
from .faults import Injector
from .trace import Tracer

MAX_EXEC_STEPS = 8


def run_workflow(task, llm, tracer: Tracer, sandbox: Sandbox, injector: Injector | None = None,
                 verify: bool = False, prefix: str = "") -> dict:
    """Run one task end to end. `prefix` namespaces artifact keys (e.g. "r/" for a restart)."""
    inj = injector or Injector(None, task)
    req = task.request()
    t0 = time.perf_counter()
    n0 = len(tracer.artifacts)
    stats ={"verify_calls": 0, "verify_rejections": 0}

    tid = tracer.add("task", "user", {"instruction": task.instruction, "request": req}, key=prefix + "task")
    init = [p for p, w in sandbox.writers.items() if w == "init"]
    if init:
        sid = tracer.add("state", "env", {p: sandbox.files[p] for p in init}, key=prefix + "state:init")
        sandbox.writers.update({p: sid for p in init})
    inj.apply_state(sandbox, tracer)

    # ---- retrieval: deterministic lookups (catalog, directory, shared budgets file) ----
    budgets_text, budgets_writer = sandbox.read("budgets.json")
    retrieval = {
        "team": task.team,
        "vendor_records": [dict(r) for r in task.catalog_records],
        "manager_email": task.manager_email,
        "budget_remaining": json.loads(budgets_text)[task.team],
    }
    rid = tracer.add("retrieval", "kb", retrieval, key=prefix + "retrieval", inputs=[tid, budgets_writer])
    retrieval, rid = inj.at("retrieval", retrieval, rid, tracer)

    def stage(name, call, inputs, sources):
        out, res = call()
        oid = tracer.add("llm_output", name, out, key=prefix + name, inputs=inputs, llm=res)
        out, oid = inj.at(name, out, oid, tracer)
        if verify:
            v, vres = agents.verify(llm, name, task.instruction, sources(), out)
            vid = tracer.add("verify", "verifier", v, key=f"{prefix}verify:{name}", inputs=[oid], llm=vres)
            stats["verify_calls"] += 1
            if not v.get("ok", True):
                stats["verify_rejections"] += 1
                out, res = call()  # one retry; transient faults do not re-fire
                oid = tracer.add("llm_output", name, out, key=f"{prefix}{name}:retry", inputs=inputs + [vid],
                                 llm=res)
                out, oid = inj.at(name, out, oid, tracer)
        return out, oid

    facts, fid = stage("researcher",
                       lambda: agents.research(llm, task.instruction, req, retrieval),
                       [tid, rid], lambda: {"retrieval": retrieval})
    plan, pid = stage("planner",
                      lambda: agents.plan(llm, task.instruction, req, facts),
                      [tid, fid], lambda: {"request": req, "facts": facts})

    # ---- executor loop ----
    history: list[dict] = []
    result_ids: list[str] = []
    for step in range(MAX_EXEC_STEPS):
        call, res = agents.execute_step(llm, req, plan, history)
        cid = tracer.add("llm_output", "executor", call, key=f"{prefix}executor#{step}",
                         inputs=[pid] + result_ids, llm=res)
        if call.get("tool") in (None, "done") or "error" in call:
            break
        result, reads, writes = sandbox.execute(call)
        spec = TOOL_SPECS.get(call["tool"], {})
        xid = tracer.add("tool_result", f"tool:{call['tool']}", {"call": call, "result": result},
                         key=f"{prefix}tool#{step}", inputs=[cid] + reads,
                         external=spec.get("external", False), reversible=spec.get("reversible", True))
        for p in writes:
            sandbox.writers[p] = xid
        if call["tool"] == "place_order":
            result, xid = inj.at("tool_result", result, xid, tracer)
        history.append({"call": call, "result": result})
        result_ids.append(xid)

    sim = sum(a.meta.get("sim_latency", 0.0) for a in tracer.artifacts[n0:])
    stats["latency_s"] = round(time.perf_counter() - t0 + sim, 4)
    return stats
