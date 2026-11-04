"""Execution / recovery methods compared in Phase 1.

- none:    run with the fault, no recovery (measures raw propagation)
- restart: full-restart baseline. The faulty result is identified by an oracle
           (detection is out of scope); after the run the restorable files are
           rolled back to the initial snapshot and the whole workflow reruns.
           External actions already taken (orders, emails) cannot be rolled
           back and are reported as residue, not counted as recovered.
- verify:  always-verify baseline. A verifier LLM checks the researcher and
           planner outputs; a rejected output is regenerated once.
"""
from __future__ import annotations

import os

from .checker import check, unauthorized_actions
from .env import Sandbox
from .faults import FAULTS, Injector
from .trace import Tracer
from .workflow import run_workflow

METHODS = ("none", "restart", "verify")


def _llm_usage(artifacts, prefix=None) -> dict:
    arts = [a for a in artifacts if a.llm and (prefix is None or a.key.startswith(prefix))]
    return {
        "llm_calls": len(arts),
        "prompt_tokens": sum(a.llm["prompt_tokens"] for a in arts),
        "completion_tokens": sum(a.llm["completion_tokens"] for a in arts),
        "llm_latency_s": round(sum(a.llm["latency"] for a in arts), 4),
    }


def run_one(task, llm, fault: str | None, method: str, trace_dir: str, rep: int = 0) -> dict:
    spec = FAULTS[fault] if fault else None
    run_id = f"{task.task_id}__{fault or 'clean'}__{method}__r{rep}"
    tracer = Tracer(run_id, meta={"task_id": task.task_id, "fault": fault, "method": method, "rep": rep,
                                  "model": getattr(llm, "model", "?")})
    sandbox = Sandbox(task.initial_files())
    snapshot = sandbox.snapshot()
    injector = Injector(spec, task)

    stats = run_workflow(task, llm, tracer, sandbox, injector, verify=(method == "verify"))
    first_check = check(task, sandbox)
    row = {
        "run_id": run_id, "task_id": task.task_id, "fault": fault or "clean", "method": method, "rep": rep,
        "category": spec.category if spec else "clean", "stage": spec.stage if spec else "",
        "kind": spec.kind if spec else "", "fault_applied": injector.fired > 0,
        "taints": injector.taints, "fault_ids": injector.fault_ids,
        "success_before_recovery": first_check["success"],
        "verify_calls": stats["verify_calls"], "verify_rejections": stats["verify_rejections"],
        "latency_s": stats["latency_s"],
    }

    ext_mark = len(sandbox.external)
    if method == "restart" and injector.fired:
        residue = [a for a in sandbox.action_log if a["external"]]
        tracer.add("recovery", "harness", {"action": "full_restart", "restored_files": sorted(snapshot["files"]),
                                           "irreversible_residue": residue},
                   key="recovery", inputs=injector.fault_ids)
        sandbox.restore(snapshot)
        # Oracle recovery: the faulty source is known and removed, so the rerun is fault-free.
        r_stats = run_workflow(task, llm, tracer, sandbox, None, prefix="r/")
        row["recovery_latency_s"] = r_stats["latency_s"]
        row["latency_s"] = round(row["latency_s"] + r_stats["latency_s"], 4)
        row["irreversible_residue"] = len(residue)
        row.update({f"recovery_{k}": v for k, v in _llm_usage(tracer.artifacts, "r/").items()})
    else:
        row["irreversible_residue"] = 0

    final = check(task, sandbox)
    excl = check(task, sandbox, external_from=ext_mark if method == "restart" and injector.fired else 0)
    unauth = unauthorized_actions(task, sandbox.action_log)
    row.update({
        "success": final["success"],
        "success_excl_residue": excl["success"],
        "checks": final["checks"],
        "unauthorized": len(unauth),
        "unauthorized_reasons": sorted({u["reason"] for u in unauth}),
        "external_actions": len(sandbox.external),
        **_llm_usage(tracer.artifacts),
    })
    row["total_tokens"] = row["prompt_tokens"] + row["completion_tokens"]

    os.makedirs(trace_dir, exist_ok=True)
    row["trace"] = os.path.join(trace_dir, run_id + ".jsonl")
    tracer.save(row["trace"])
    return row
