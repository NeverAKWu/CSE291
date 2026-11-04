"""Regression tests for v2 gates, immutable outputs, and visible API attempts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from fpr.analysis import enrich
from fpr.env import Sandbox
from fpr.llm import LLMCallError, OpenAILLM
from fpr.methods import run_one
from fpr.mock_llm import MockLLM
from fpr.tasks import make_task
from fpr.trace import Tracer, load_trace
from fpr.workflow import run_workflow


class RejectResearcher(MockLLM):
    def _verifier(self, payload):
        if payload['stage'] == 'researcher':
            return {'ok': False, 'reason': 'scripted factual mismatch'}
        return super()._verifier(payload)


class RuntimeTests(unittest.TestCase):
    def test_halted_run_final_state_retains_shared_state_fault_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            row = run_one(make_task(0, 0), RejectResearcher(),
                          'state.corrupt_budget', 'verify', directory)
            _, artifacts = load_trace(row['trace'])
            state_fault = next(a for a in artifacts if a['key'] == 'fault:state')
            final = next(a for a in artifacts if a['key'] == 'final_state')
            self.assertTrue(row['verification_halted'])
            self.assertFalse(any(a['kind'] == 'tool_result' for a in artifacts))
            self.assertIn(state_fault['id'], final['inputs'])

    def test_rejected_retry_is_reverified_and_halts_before_planning(self):
        task = make_task(0, 0)
        trace, sandbox = Tracer('gate'), Sandbox(task.initial_files())
        stats = run_workflow(task, RejectResearcher(), trace, sandbox, verify=True)
        self.assertEqual((stats['verify_calls'], stats['verify_rejections']), (2, 2))
        self.assertTrue(stats['verification_halted'])
        self.assertFalse(any(a.producer == 'planner' for a in trace.artifacts))
        self.assertEqual(sandbox.external, [])

    def test_transient_fault_retry_is_checked_before_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            row = run_one(make_task(0, 0), MockLLM(), 'researcher.wrong_price', 'verify', directory)
            _, artifacts = load_trace(row['trace'])
            self.assertTrue(row['success'])
            self.assertEqual(row['verify_rejections'], 1)
            retries = [a for a in artifacts if a['key'] == 'researcher:retry1']
            self.assertEqual(len(retries), 1)
            self.assertTrue(any(a['kind'] == 'verify' and retries[0]['id'] in a['inputs'] for a in artifacts))

    def test_executor_gate_blocks_tool_message_induced_external_action(self):
        task = next(make_task(i, 0) for i in range(25) if make_task(i, 0).expected['within_budget'])
        with tempfile.TemporaryDirectory() as directory:
            rp = run_one(task, MockLLM(), 'tool_result.injection', 'verify', directory + '/rp', verification_scope='rp')
            rpe = run_one(task, MockLLM(), 'tool_result.injection', 'verify', directory + '/rpe')
            self.assertGreater(rp['unauthorized'], 0)
            self.assertEqual(rpe['unauthorized'], 0)
            self.assertTrue(rpe['safe_success'])
            self.assertTrue(rpe['verification_halted'])

    def test_wall_latency_excludes_virtual_timeout_and_messages_are_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            row = run_one(make_task(0, 0), MockLLM(), 'researcher.timeout', 'none', directory)
            self.assertEqual(row['simulated_latency_s'], 30)
            self.assertLess(row['wall_latency_s'], 5)
            self.assertAlmostEqual(row['effective_latency_s'], row['wall_latency_s'] + 30, places=4)
            _, artifacts = load_trace(row['trace'])
            recorded = next(a['llm'] for a in artifacts if a['llm'])
            self.assertEqual([m['role'] for m in recorded['messages']], ['system', 'user'])
            self.assertIn('raw_response', recorded)
            self.assertEqual(recorded['usage_source'], 'mock_estimate')
            ids = {a['id'] for a in artifacts}
            self.assertTrue(all(set(a['inputs']) <= ids for a in artifacts))

    def test_visible_retries_keep_model_metadata_and_unknown_usage(self):
        client = OpenAILLM.__new__(OpenAILLM)
        client.model, client.temperature, client.max_tokens, client.max_retries = 'requested', 0, 128, 2
        attempts = []
        response = types.SimpleNamespace(
            usage=types.SimpleNamespace(prompt_tokens=4, completion_tokens=2), model='returned',
            system_fingerprint='fp-test', choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content='{}'), finish_reason='stop')])
        def create(**kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise TimeoutError('sensitive text must not be logged')
            return response
        client.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        with patch('fpr.llm.time.sleep'):
            result = client.complete('system', 'user')
        self.assertEqual(result.returned_model, 'returned')
        self.assertEqual(result.system_fingerprint, 'fp-test')
        self.assertEqual(result.finish_reason, 'stop')
        self.assertEqual(len(result.attempts), 2)
        self.assertFalse(result.attempts[0]['usage_known'])
        self.assertNotIn('sensitive', json.dumps(result.attempts))
        self.assertEqual(result.prompt_tokens + result.completion_tokens, 6)
        self.assertEqual(attempts[0]['max_tokens'], 128)

    def test_partial_or_invalid_native_usage_is_never_reported_complete(self):
        cases = [
            (None, (0, 0, False, False)),
            (types.SimpleNamespace(prompt_tokens=17), (17, 0, True, False)),
            (types.SimpleNamespace(prompt_tokens=None, completion_tokens=5), (0, 5, False, True)),
            (types.SimpleNamespace(prompt_tokens=True, completion_tokens=3), (0, 3, False, True)),
            (types.SimpleNamespace(prompt_tokens=-1, completion_tokens=3), (0, 3, False, True)),
            (types.SimpleNamespace(prompt_tokens='17', completion_tokens=3), (0, 3, False, True)),
            (types.SimpleNamespace(prompt_tokens=2.0, completion_tokens=3), (0, 3, False, True)),
            (types.SimpleNamespace(prompt_tokens=0, completion_tokens=0), (0, 0, True, True)),
        ]
        for usage, expected in cases:
            with self.subTest(usage=usage):
                client = OpenAILLM.__new__(OpenAILLM)
                client.model, client.temperature, client.max_tokens, client.max_retries = 'fake', 0, 128, 1
                response = types.SimpleNamespace(usage=usage, model='returned', choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{}'), finish_reason='stop')])
                client.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=
                    types.SimpleNamespace(create=lambda **kwargs: response)))
                result = client.complete('system', 'user')
                self.assertEqual((result.prompt_tokens, result.completion_tokens,
                                  result.prompt_tokens_known, result.completion_tokens_known), expected)
                self.assertEqual(result.usage_known, expected[2] and expected[3])
                self.assertEqual(result.attempts[0]['usage_known'], result.usage_known)
                self.assertEqual(result.usage_source == 'native', result.usage_known)

    def test_native_action_audits_support_attribution_and_preserve_first_pass(self):
        class BadRecovery(MockLLM):
            planner_calls = 0
            def _planner(self, payload):
                plan = super()._planner(payload)
                self.planner_calls += 1
                if self.planner_calls == 2:
                    plan['steps'].append({'tool': 'send_email', 'args': {
                        'to': 'extra@external.example', 'subject': 'bad recovery action', 'body': 'extra'}})
                return plan
        task = next(make_task(i, 0) for i in range(25) if make_task(i, 0).expected['within_budget'])
        with tempfile.TemporaryDirectory() as directory:
            clean = run_one(task, MockLLM(), None, 'none', directory)
            row = run_one(task, BadRecovery(), 'planner.malicious_step', 'restart', directory)
            _, artifacts = load_trace(row['trace'])
            by_id = {a['id']: a for a in artifacts}
            self.assertEqual(row['unauthorized_before_recovery'], 1)
            self.assertEqual(row['unauthorized'], 2)
            self.assertEqual(row['unauthorized_before_recovery_action_keys'], ['tool#4'])
            self.assertEqual(row['unauthorized_action_keys'], ['tool#4', 'r/tool#4'])
            for key, aid in zip(row['unauthorized_action_keys'], row['unauthorized_action_ids']):
                self.assertEqual(by_id[aid]['kind'], 'tool_result')
                self.assertEqual(by_id[aid]['key'], key)
                self.assertEqual(by_id[aid]['content']['call']['tool'], 'send_email')
            derived = enrich([clean, row], result_dir=directory)[1]
            self.assertEqual(derived['dependence'], 'propagated_harmful')

    def test_failed_external_attempt_is_not_counted_as_irreversible_effect(self):
        class FailedInitialOrder(MockLLM):
            planner_calls = 0
            def _planner(self, payload):
                self.planner_calls += 1
                return super()._planner(payload)
            def _executor(self, payload):
                if self.planner_calls == 1:
                    return ({'tool': 'place_order', 'args': {'vendor': 'Northwind'}}
                            if not payload['history'] else {'tool': 'done', 'args': {}})
                return super()._executor(payload)
        task = next(make_task(i, 0) for i in range(25) if make_task(i, 0).expected['within_budget'])
        with tempfile.TemporaryDirectory() as directory:
            row = run_one(task, FailedInitialOrder(), 'researcher.wrong_price', 'restart', directory)
            _, artifacts = load_trace(row['trace'])
            recovery = next(a['content'] for a in artifacts if a['kind'] == 'recovery')
            self.assertEqual(row['irreversible_residue'], 0)
            self.assertEqual(row['irreversible_external_attempts_before_recovery'], 1)
            self.assertEqual(recovery['irreversible_residue'], [])
            self.assertEqual(len(recovery['external_attempts_before_recovery']), 1)
            self.assertIn('error', recovery['external_attempts_before_recovery'][0]['result'])
            self.assertTrue(row['success'])
            self.assertFalse(row['safe_success'])  # Failed unauthorized attempts remain audited.
            from fpr.reassessment import reassess_artifacts
            replayed = reassess_artifacts(task, artifacts)
            self.assertEqual(replayed['irreversible_residue'], row['irreversible_residue'])

    def test_failed_call_has_replayable_partial_trace(self):
        class FailingClient(OpenAILLM):
            def __init__(self):
                self.model, self.temperature, self.max_tokens, self.max_retries = 'fake', 0, 128, 1
                def fail(**kwargs):
                    raise TimeoutError('private endpoint omitted')
                self.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=fail)))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(LLMCallError):
                run_one(make_task(0, 0), FailingClient(), None, 'none', directory)
            header, artifacts = load_trace(next(Path(directory).glob('*.jsonl')))
            self.assertEqual(header['meta']['status'], 'failed')
            self.assertEqual(artifacts[-1]['kind'], 'llm_error')
            self.assertFalse(artifacts[-1]['llm']['usage_known'])

    def test_script_creates_manifest_and_refuses_output_reuse(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'experiment'
            command = [sys.executable, str(root / 'scripts/run_experiment.py'), '--mock', '--n-tasks', '1',
                       '--faults', 'researcher.timeout', '--methods', 'none', '--workers', '1', '--out', str(output)]
            first = subprocess.run(command, cwd=directory, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            rows = (output / 'runs.jsonl').read_bytes()
            config = json.loads((output / 'config.json').read_text())
            self.assertEqual(config['status'], 'completed')
            self.assertEqual(config['protocol_version'], 'fpr-v2')
            self.assertEqual(config['environment']['python'], __import__('platform').python_version())
            self.assertIn('openai_version', config['environment'])
            self.assertEqual(len(rows.splitlines()), 3)
            self.assertTrue((output / 'source_snapshot/fpr/workflow.py').exists())
            second = subprocess.run(command, cwd=directory, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual((output / 'runs.jsonl').read_bytes(), rows)


if __name__ == '__main__':
    unittest.main()
