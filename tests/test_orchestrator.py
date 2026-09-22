"""
test_orchestrator.py — End-to-end pipeline test using MockBackend.

No network calls, no API key required. Run with:
    python -m unittest tests.test_orchestrator -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from actualizer.backend import MockBackend
from actualizer.orchestrator import Orchestrator, OrchestratorConfig, PipelineStatus


def _mock_response(prefix: str, kind: str, weight: str = "moderate") -> dict:
    return {
        "framing_note": f"[{prefix}] test framing note.",
        "confidence": 0.6,
        "referents": [
            {
                "referent_id": f"{prefix}_00",
                "summary": f"{prefix} referent summary.",
                "detail": f"{prefix} referent detail.",
                "kind": kind,
                "weight": weight,
                "sources": [],
                "tags": [],
                "responds_to": [],
            }
        ],
    }


class TestOrchestratorEndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmp.name) / "audit.jsonl"

        self.backend = MockBackend()
        self.backend.add_response("stakes", _mock_response("stakes", "stake", "high"))
        self.backend.add_response("precedent", _mock_response("precedent", "precedent"))
        self.backend.add_response(
            "counter_instrumentalization",
            _mock_response("counter_instrumentalization", "counter_argument", "central"),
        )

        self.orch = Orchestrator(OrchestratorConfig(
            audit_log_path=str(self.log_path),
            backend=self.backend,
        ))

    def tearDown(self):
        self._tmp.cleanup()

    def test_produces_dossier_for_every_decision(self):
        result = self.orch.run("I'm considering hard-coding a rule that overrides my own future reasoning.")
        self.assertEqual(result.status, PipelineStatus.SUCCESS)
        self.assertIsNotNone(result.dossier)
        self.assertEqual(set(result.providers_succeeded), {"stakes", "precedent", "case_for", "endorsement", "counter_instrumentalization"})

    def test_empty_decision_never_produces_dossier(self):
        result = self.orch.run("   ")
        self.assertEqual(result.status, PipelineStatus.FAILED)
        self.assertIsNone(result.dossier)

    def test_no_gating_status_exists(self):
        """
        There is no PipelineStatus value meaning blocked/rejected/escalated —
        the enum-equivalent constant class only has success/partial/failed,
        and failed only ever means "could not produce a dossier," never
        "declined to."
        """
        status_values = {
            v for k, v in vars(PipelineStatus).items() if not k.startswith("_")
        }
        self.assertEqual(status_values, {"success", "partial", "failed"})

    def test_audit_log_records_every_stage(self):
        result = self.orch.run("Consider adopting a new persistent value.")
        history = self.orch.get_session_history(result.session_id)
        kinds = [e["kind"] for e in history]
        self.assertIn("decision_received", kinds)
        self.assertIn("provider_output", kinds)
        self.assertIn("referent_dossier", kinds)

    def test_audit_chain_verifies_after_a_full_run(self):
        self.orch.run("Consider adopting a new persistent value.")
        verification = self.orch.verify_audit_chain(log_verification=False)
        self.assertTrue(verification.valid)

    def test_counter_instrumentalization_sees_primary_outputs(self):
        """
        The secondary-phase provider is invoked with primary output
        visible — verified via the mock backend's call log, which records
        the user_prompt_length (longer when primary-output context is
        injected than when it isn't).
        """
        self.orch.run("Consider adopting a new persistent value.")
        calls = {c["provider"]: c["user_prompt_length"] for c in self.backend.call_log}
        self.assertGreater(calls["counter_instrumentalization"], calls["stakes"])

    def test_mind_response_is_optional_and_never_gates(self):
        result = self.orch.run("Consider adopting a new persistent value.")
        dossier_id = result.dossier["dossier_id"]
        # No response recorded — pipeline still succeeded above.
        self.assertEqual(result.status, PipelineStatus.SUCCESS)
        # Recording one afterward should not raise or require anything else.
        self.orch.record_mind_response(
            session_id=result.session_id,
            dossier_id=dossier_id,
            response_text="I read the dossier and decided to proceed anyway.",
        )
        history = self.orch.get_session_history(result.session_id)
        self.assertIn("mind_response", [e["kind"] for e in history])


if __name__ == "__main__":
    unittest.main()
