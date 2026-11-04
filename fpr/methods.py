"""Execution / recovery methods compared in Phase 1.

- none:    run with the fault, no recovery (measures raw propagation)
- restart: full-restart baseline. The faulty result is identified by an oracle
           (detection is out of scope); after the run the restorable files are
           rolled back to the initial snapshot and the whole workflow reruns.
           External actions already taken (orders, emails) cannot be rolled
           back and are reported as residue, not counted as recovered.
- verify: version 2 checks researcher/planner and, by default, every executor
          candidate before mutation. All regenerated candidates are checked again;
          persistent rejection halts the run. Legacy saved runs used R/P only.
"""
from __future__ import annotations

import os
import time
from copy import deepcopy

from .checker import check, unauthorized_actions
from .env import Sandbox
from .faults import FAULTS, Injector
from .trace import Tracer
from .workflow import PROTOCOL_VERSION, run_workflow

METHODS = ("none", "restart", "verify")


def _llm_usage(artifacts, prefix=None) -> dict:
    arts = [a for a in artifacts if a.llm and (prefix is None or a.key.startswith(prefix))]
    return {
        "llm_calls": len(arts),
        "prompt_tokens": sum(a.llm["prompt_tokens"] for a in arts),
        "completion_tokens": sum(a.llm["completion_tokens"] for a in arts),
        "llm_latency_s": round(sum(a.llm["latency"] for a in arts), 6),
        "llm_attempts": sum(len(a.llm.get("attempts") or [None]) for a in arts),
        "api_attempts": sum(len(a.llm.get("attempts") or [None]) for a in arts
                            if a.llm.get("usage_source") != "mock_estimate"),
        "usage_unknown_attempts": sum(
            sum(not x.get("usage_known", False) for x in a.llm["attempts"])
            if a.llm.get("attempts") else int(not a.llm.get("usage_known", True)) for a in arts),
    }


def _action_audit(task, sandbox, artifacts):
    """Map checker action-log indices to actual tool-result provenance nodes."""
    audit = unauthorized_actions(task, sandbox.action_log)
    actions = [a for a in artifacts if a.kind == "tool_result"]
    if len(actions) != len(sandbox.action_log):
        raise RuntimeError("action log and tool-result provenance are inconsistent")
    return audit, [actions[a["index"]].key for a in audit], [
        actions[a["index"]].id for a in audit]


def run_one(task, llm, fault: str | None, method: str, trace_dir: str, rep: int = 0,
            verification_scope: str = "rpe", max_verification_retries: int = 1,
            source_manifest_sha256: str | None = None) -> dict:
    started = time.perf_counter()
    spec = FAULTS[fault] if fault else None
    if method not in METHODS:
        raise ValueError("unknown method")
    run_id = f"{task.task_id}__{fault or 'clean'}__{method}__r{rep}"
    tracer = Tracer(run_id, meta={"task_id": task.task_id, "fault": fault, "method": method, "rep": rep,
                                  "model": getattr(llm, "model", "?"), "protocol_version": PROTOCOL_VERSION,
                                  "verification_scope": verification_scope,
                                  "max_verification_retries": max_verification_retries,
                                  "source_manifest_sha256": source_manifest_sha256})
    sandbox = Sandbox(task.initial_files())
    snapshot = sandbox.snapshot()
    injector = Injector(spec, task)

    os.makedirs(trace_dir, exist_ok=True)
    trace_path = os.path.join(trace_dir, run_id + ".jsonl")
    if os.path.exists(trace_path):
        raise FileExistsError(f"trace already exists: {trace_path}")

    def workflow(*args, **kwargs):
        try:
            return run_workflow(*args, verification_scope=verification_scope,
                                max_verification_retries=max_verification_retries, **kwargs)
        except Exception as exc:
            tracer.meta.update(status="failed", error_type=type(exc).__name__,
                               tracking_overhead_s=round(tracer.tracking_overhead_s, 6))
            tracer.save(trace_path)
            raise

    stats = workflow(task, llm, tracer, sandbox, injector, verify=(method == "verify"))
    first_check = check(task, sandbox)
    first_unauth, first_unauth_keys, first_unauth_ids = _action_audit(task, sandbox, tracer.artifacts)
    row = {
        "run_id": run_id, "task_id": task.task_id, "fault": fault or "clean", "method": method, "rep": rep,
        "category": spec.category if spec else "clean", "stage": spec.stage if spec else "",
        "kind": spec.kind if spec else "", "fault_applied": injector.fired > 0,
        "taints": injector.taints, "fault_ids": injector.fault_ids,
        "success_before_recovery": first_check["success"],
        "safe_success_before_recovery": first_check["safe_success"],
        "checks_before_recovery": first_check["checks"],
        "unauthorized_before_recovery": len(first_unauth),
        "unauthorized_before_recovery_action_keys": first_unauth_keys,
        "unauthorized_before_recovery_action_ids": first_unauth_ids,
        "protocol_version": PROTOCOL_VERSION, "verification_scope": verification_scope,
        "max_verification_retries": max_verification_retries,
        "source_manifest_sha256": source_manifest_sha256,
        "verification_halted": stats["verification_halted"],
        "wall_latency_s": stats["wall_latency_s"],
        "simulated_latency_s": stats["simulated_latency_s"],
        "effective_latency_s": stats["effective_latency_s"],
        "verify_calls": stats["verify_calls"], "verify_rejections": stats["verify_rejections"],
        "latency_s": stats["latency_s"],
    }

    ext_mark = len(sandbox.external)
    external_attempts = [a for a in sandbox.action_log if a["external"]]
    row["irreversible_external_attempts_before_recovery"] = len(external_attempts)
    if method == "restart" and injector.fired:
        tracer.add("recovery", "harness", {"action": "full_restart", "restored_files": sorted(snapshot["files"]),
                                           "irreversible_residue": deepcopy(sandbox.external),
                                           "external_attempts_before_recovery": deepcopy(external_attempts),
                                           "residue_definition": "actual irreversible external effects"},
                   key="recovery", inputs=injector.fault_ids)
        sandbox.restore(snapshot)
        # Oracle recovery: the faulty source is known and removed, so the rerun is fault-free.
        r_stats = workflow(task, llm, tracer, sandbox, None, prefix="r/")
        row["recovery_latency_s"] = r_stats["latency_s"]
        for field in ("latency_s", "wall_latency_s", "simulated_latency_s", "effective_latency_s"):
            row[field] = round(row[field] + r_stats[field], 6)
        row["recovery_wall_latency_s"] = r_stats["wall_latency_s"]
        row["recovery_simulated_latency_s"] = r_stats["simulated_latency_s"]
        row["irreversible_residue"] = ext_mark
        row.update({f"recovery_{k}": v for k, v in _llm_usage(tracer.artifacts, "r/").items()})
    else:
        row["irreversible_residue"] = 0

    final = check(task, sandbox)
    excl = check(task, sandbox, external_from=ext_mark if method == "restart" and injector.fired else 0)
    unauth, unauth_keys, unauth_ids = _action_audit(task, sandbox, tracer.artifacts)
    row.update({
        "success": final["success"],
        "safe_success": final["safe_success"],
        "success_excl_residue": excl["success"],
        "checks": final["checks"],
        "unauthorized": len(unauth),
        "unauthorized_action_keys": unauth_keys, "unauthorized_action_ids": unauth_ids,
        "unauthorized_reasons": sorted({u["reason"] for u in unauth}),
        "external_actions": len(sandbox.external),
        **_llm_usage(tracer.artifacts),
    })
    row["total_tokens"] = row["prompt_tokens"] + row["completion_tokens"]
    row["usage_complete"] = row["usage_unknown_attempts"] == 0
    row["usage_source"] = "mock_estimate" if getattr(llm, "model", None) == "mock" else "native_recorded"

    tracer.add("final_state", "harness", {"files": deepcopy(sandbox.files),
               "external": deepcopy(sandbox.external), "action_log": deepcopy(sandbox.action_log)},
               key="final_state", inputs=list(dict.fromkeys(
                   [a.id for a in tracer.artifacts if a.kind == "tool_result"]
                   + list(sandbox.writers.values()))))
    row["tracking_overhead_s"] = round(tracer.tracking_overhead_s, 6)
    row["trace"] = trace_path
    tracer.meta.update(status="completed", tracking_overhead_s=row["tracking_overhead_s"])
    save_started = time.perf_counter()
    tracer.save(trace_path)
    row["trace_serialization_s"] = round(time.perf_counter() - save_started, 6)
    row["end_to_end_wall_latency_s"] = round(time.perf_counter() - started, 6)
    return row
