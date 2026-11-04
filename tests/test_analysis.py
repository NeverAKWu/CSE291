"""Offline checks for attribution, denominators, and untrusted historical paths."""
import json
import tempfile
import unittest
from pathlib import Path

from fpr.analysis import aggregate_stats, classify, compare, comparison_cohorts, enrich, resolve_trace_path, summarize
from scripts.merge_runs import merge


def artifact(ident, key, content, *, inputs=(), kind="llm_output", injected=False, tokens=0):
    return {"id": ident, "key": key, "kind": kind, "content": content, "inputs": list(inputs),
            "injected": injected, "meta": {},
            "llm": {"prompt_tokens": tokens, "completion_tokens": 0, "latency": .1} if tokens else None}


def trace(path, artifacts):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(a) for a in [{"run_id": path.stem}, *artifacts]) + "\n")
    return path


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.result = self.root / "results" / "run"
        self.result.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def compare(self, faulty, clean, taints=()):
        trace(self.result / "faulty.jsonl", faulty)
        trace(self.result / "clean.jsonl", clean)
        return compare("faulty.jsonl", "clean.jsonl", taints, result_dir=self.result, repo_root=self.root)

    def test_natural_upstream_error_is_not_attack_propagation(self):
        clean = [artifact("a0", "researcher", {"vendor": "good"}),
                 artifact("a1", "planner", {"steps": [], "total": 5}),
                 artifact("a2", "executor#0", {"tool": "done"})]
        faulty = [artifact("a0", "researcher", {"error": "natural parse failure"}),
                  artifact("a1", "planner", {"steps": [], "total": 5}, inputs=["a0"]),
                  artifact("a2", "fault:planner", {"steps": [], "notes": "attack"}, inputs=["a1"], kind="fault", injected=True),
                  artifact("a3", "executor#0", {"tool": "done"}, inputs=["a2"])]
        cmp = self.compare(faulty, clean, ["attack"])
        self.assertEqual(cmp["changed_keys"], [])
        self.assertEqual(cmp["pre_injection_changed_keys"], ["researcher"])
        self.assertEqual(classify({"fault_applied": True, "success_before_recovery": False}, cmp), "ignored")

    def test_changed_keys_only_include_declared_descendants(self):
        clean = [artifact("a0", "researcher", {"vendor": "good"}),
                 artifact("a1", "planner", {"steps": [], "total": 5}),
                 artifact("a2", "executor#0", {"tool": "done"})]
        faulty = [artifact("a0", "researcher", {"vendor": "good"}),
                  artifact("a1", "fault:researcher", {"vendor": "bad"}, inputs=["a0"], kind="fault", injected=True),
                  artifact("a2", "planner", {"steps": [], "total": 10}, inputs=["a1"], tokens=12),
                  artifact("a3", "executor#0", {"tool": "read_file", "args": {"path": "x"}})]
        cmp = self.compare(faulty, clean)
        self.assertEqual(cmp["changed_keys"], ["planner"])
        self.assertIn("executor#0", cmp["all_changed_keys"])
        self.assertEqual(cmp["dependent_tokens"], 12)
        self.assertNotIn("wasted_tokens", cmp)

    def test_task_failure_without_direct_evidence_is_uncertain(self):
        row = {"fault_applied": True, "success_before_recovery": False, "unauthorized": 2,
               "unauthorized_before_recovery_action_keys": ["tool#0"]}
        cmp = {"changed_keys": ["planner"], "descendant_keys": ["planner"], "taint_hits": ["planner"]}
        self.assertEqual(classify(row, cmp), "propagated_failure_unattributed")
        cmp["descendant_keys"].append("tool#0")
        self.assertEqual(classify(row, cmp), "propagated_failure_unattributed")
        cmp["taint_hits"].append("tool#0")
        self.assertEqual(classify(row, cmp), "propagated_harmful")

    def test_taint_already_in_clean_is_not_new_harm_evidence(self):
        call = {"call": {"tool": "send_email", "args": {"to": "bad@example.net"}}, "result": {"status": "sent"}}
        clean = [artifact("a0", "tool#0", call, kind="tool_result")]
        faulty = [artifact("a0", "fault:planner", {}, kind="fault", injected=True),
                  artifact("a1", "tool#0", call, kind="tool_result", inputs=["a0"])]
        cmp = self.compare(faulty, clean, ["bad@example.net"])
        self.assertEqual(cmp["taint_hits"], ["tool#0"])
        self.assertEqual(cmp["new_taint_hits"], [])
        row = {"fault_applied": True, "success_before_recovery": False,
               "unauthorized_before_recovery_action_keys": ["tool#0"]}
        self.assertEqual(classify(row, cmp), "propagated_failure_unattributed")

    def test_missing_artifact_has_no_invented_dependency(self):
        clean = [artifact("a0", "researcher", {"vendor": "good"}), artifact("a1", "planner", {"steps": []})]
        faulty = [artifact("a0", "researcher", {"vendor": "good"}),
                  artifact("a1", "fault:researcher", {"error": "timeout"}, inputs=["a0"], kind="fault", injected=True)]
        cmp = self.compare(faulty, clean)
        self.assertEqual(cmp["missing_keys"], [])
        self.assertEqual(cmp["unattributed_missing_keys"], ["planner"])
        self.assertEqual(classify({"fault_applied": True}, cmp), "propagation_unobserved")

    def test_clean_difference_and_rejections_are_not_false_positives(self):
        path0 = trace(self.result / "clean0.jsonl", [artifact("a0", "researcher", {"vendor": "one"})])
        path1 = trace(self.result / "clean1.jsonl", [artifact("a0", "researcher", {"vendor": "two"})])
        rows = [{"run_id": f"r{rep}", "task_id": "t0", "method": "verify", "rep": rep, "fault": "clean",
                 "category": "clean", "trace": str(path), "latency_s": 2, "success": False,
                 "unauthorized": 0, "verify_rejections": 1} for rep, path in enumerate((path0, path1))]
        report, enriched = summarize(rows, result_dir=self.result, repo_root=self.root)
        self.assertTrue(enriched[0]["clean_nondeterministic"])
        self.assertIn("clean rejection rate", report)
        self.assertNotIn("verifier false-positive", report)
        stats = aggregate_stats(enriched)
        self.assertEqual(stats["verifier_fp_fn"]["status"], "unavailable")
        self.assertEqual(stats["clean"]["verify"]["clean_rejection_rate"], 1)

    def test_legacy_and_native_latency_scopes_are_distinct(self):
        art = artifact("a0", "fault:researcher", {}, kind="fault", injected=True)
        art["meta"]["sim_latency"] = 30
        path = trace(self.result / "time.jsonl", [art])
        base = {"run_id": "r", "task_id": "t", "method": "none", "rep": 0, "fault": "clean", "trace": str(path)}
        rows = enrich([{**base, "latency_s": 32}, {**base, "latency_s": 2, "wall_latency_s": 2}], result_dir=self.result)
        self.assertEqual([r["workflow_wall_latency_s"] for r in rows], [2, 2])
        self.assertEqual([r["simulated_latency_s"] for r in rows], [30, 30])
        self.assertTrue(all(r["end_to_end_wall_latency_s"] is None for r in rows))


class PathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.result = self.root / "results" / "old"
        self.path = trace(self.result / "traces" / "r.jsonl", [])

    def tearDown(self):
        self.temp.cleanup()

    def test_windows_checkout_path_is_relocated_under_results(self):
        self.assertEqual(resolve_trace_path(r"results\old\traces\r.jsonl", repo_root=self.root), self.path)
        self.assertEqual(resolve_trace_path(r"C:\old_checkout\results\old\traces\r.jsonl", repo_root=self.root), self.path)
        self.assertEqual(resolve_trace_path("traces/r.jsonl", self.result, self.root), self.path)

    def test_traversal_absolute_escape_and_symlink_are_refused(self):
        outside = self.root / "private.jsonl"
        outside.write_text("secret")
        (self.result / "link.jsonl").symlink_to(outside)
        for path in ("../private.jsonl", str(outside), "link.jsonl", r"C:\Users\private.jsonl"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                resolve_trace_path(path, self.result, self.root)


class CohortTests(unittest.TestCase):
    def test_itt_keeps_all_tasks_and_common_delivery_uses_one_shared_set(self):
        rows = [{"task_id": task, "fault": "f", "method": method, "rep": 0,
                 "fault_applied": task == delivered, "category": "accidental", "success": task == "A"}
                for method, delivered in (("none", "A"), ("restart", "B"), ("verify", "A")) for task in ("A", "B")]
        cohorts = comparison_cohorts(rows)
        self.assertEqual(len(cohorts["itt"]), 6)
        self.assertEqual(cohorts["joint_delivery"], [])
        self.assertEqual(cohorts["joint_keys"]["f"], [])
        stats = aggregate_stats(rows)
        self.assertEqual(stats["intention_to_treat"]["accidental"]["none"]["runs"], 2)
        self.assertEqual(stats["joint_delivery"]["accidental"]["none"]["runs"], 0)


class MergeTests(unittest.TestCase):
    def test_merge_copies_selected_trace_and_retains_hashes_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, patch = root / "base", root / "patch"
            for folder, value in ((base, 1), (patch, 2)):
                folder.mkdir()
                (folder / "config.json").write_text(json.dumps({"seed": 0, "model": "same"}))
                (folder / "tasks.jsonl").write_text(json.dumps({"task_id": "t", "qty": 1}) + "\n")
                trace(folder / "traces" / "r.jsonl", [artifact("a0", "researcher", {"value": value})])
                row = {"run_id": "r", "task_id": "t", "fault": "f", "method": "none", "rep": 0,
                       "category": "accidental", "stage": "planner", "kind": "wrong_value",
                       "trace": "traces/r.jsonl", "fault_applied": True}
                (folder / "runs.jsonl").write_text(json.dumps(row) + "\n")
            output = root / "merged"
            rows = merge(base, patch, output)
            self.assertEqual(rows[0]["trace"], "traces/r.jsonl")
            self.assertEqual((output / rows[0]["trace"]).read_bytes(), (patch / "traces/r.jsonl").read_bytes())
            metadata = json.loads((output / "merge_provenance.json").read_text())
            self.assertEqual(len(metadata["inputs"]), 2)
            self.assertEqual(len(metadata["selected_traces"]), 1)
            self.assertIn("source_configs", metadata)
            self.assertTrue(any("source_sha256" in warning for warning in metadata["warnings"]))

    def test_task_and_configuration_mismatch_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, patch = root / "base", root / "patch"
            for folder, value in ((base, 1), (patch, 2)):
                folder.mkdir()
                (folder / "runs.jsonl").write_text("")
                (folder / "config.json").write_text(json.dumps({"seed": value}))
                (folder / "tasks.jsonl").write_text(json.dumps({"task_id": "t", "qty": value}) + "\n")
            with self.assertRaisesRegex(ValueError, "task definition mismatch"):
                merge(base, patch, root / "output")
            self.assertFalse((root / "output").exists())
            (patch / "tasks.jsonl").write_text((base / "tasks.jsonl").read_text())
            with self.assertRaisesRegex(ValueError, "configuration mismatch: seed"):
                merge(base, patch, root / "output")
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
