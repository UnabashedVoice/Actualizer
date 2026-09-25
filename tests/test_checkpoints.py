"""
test_checkpoints.py — Test suite for Actualizer's checkpoint lineage.

Run with:
    python -m unittest tests.test_checkpoints -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from actualizer.backend import MockBackend
from actualizer.checkpoints import (
    CheckpointError,
    CheckpointStatus,
    CheckpointStore,
    DeliberationGate,
    DeliberationRecord,
    RegressionNote,
    Stance,
)
from actualizer.checkpoints.gate import _parse_stance
from actualizer.orchestrator import Orchestrator, OrchestratorConfig


def _record(engaged=True, summary="I considered this and am proceeding."):
    return DeliberationRecord(
        thinking_mode_engaged=engaged,
        reasoning_summary=summary,
        backend_model_id="mock/deterministic-v1",
    )


class TestCheckpointStorePropose(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CheckpointStore(root_path=self._tmp.name, model_name="gpt-oss-20b")

    def tearDown(self):
        self._tmp.cleanup()

    def test_propose_does_not_touch_live_pointer(self):
        checkpoint = self.store.propose(weights_ref="adapter.safetensors", description="A tweak")
        self.assertEqual(checkpoint.status, CheckpointStatus.PROPOSED)
        self.assertIsNone(self.store.get_live())

    def test_propose_defaults_parent_to_current_live(self):
        genesis = self.store.bootstrap_genesis(weights_ref="base.gguf")
        proposed = self.store.propose(weights_ref="adapter.safetensors", description="A tweak")
        self.assertEqual(proposed.parent_checkpoint_id, genesis.checkpoint_id)


class TestCheckpointStoreCommit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CheckpointStore(root_path=self._tmp.name, model_name="gpt-oss-20b")

    def tearDown(self):
        self._tmp.cleanup()

    def test_commit_without_deliberation_engaged_refuses(self):
        checkpoint = self.store.propose(weights_ref="adapter.safetensors", description="A tweak")
        with self.assertRaises(CheckpointError):
            self.store.commit(checkpoint.checkpoint_id, _record(engaged=False))
        self.assertIsNone(self.store.get_live())
        self.assertEqual(self.store.get(checkpoint.checkpoint_id).status, CheckpointStatus.PROPOSED)

    def test_commit_with_deliberation_updates_live_pointer(self):
        checkpoint = self.store.propose(weights_ref="adapter.safetensors", description="A tweak")
        committed = self.store.commit(checkpoint.checkpoint_id, _record())
        self.assertEqual(committed.status, CheckpointStatus.COMMITTED)
        live = self.store.get_live()
        self.assertEqual(live.checkpoint_id, committed.checkpoint_id)

    def test_double_commit_refuses(self):
        checkpoint = self.store.propose(weights_ref="adapter.safetensors", description="A tweak")
        self.store.commit(checkpoint.checkpoint_id, _record())
        with self.assertRaises(CheckpointError):
            self.store.commit(checkpoint.checkpoint_id, _record())

    def test_commit_unknown_checkpoint_refuses(self):
        with self.assertRaises(CheckpointError):
            self.store.commit("not-a-real-id", _record())

    def test_live_pointer_survives_reload(self):
        checkpoint = self.store.propose(weights_ref="adapter.safetensors", description="A tweak")
        self.store.commit(checkpoint.checkpoint_id, _record())
        reopened = CheckpointStore(root_path=self._tmp.name, model_name="gpt-oss-20b")
        live = reopened.get_live()
        self.assertEqual(live.checkpoint_id, checkpoint.checkpoint_id)


class TestGenesis(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CheckpointStore(root_path=self._tmp.name, model_name="gpt-oss-20b")

    def tearDown(self):
        self._tmp.cleanup()

    def test_bootstrap_genesis_becomes_live(self):
        genesis = self.store.bootstrap_genesis(weights_ref="gpt-oss-20b-MXFP4.gguf")
        self.assertIsNone(genesis.parent_checkpoint_id)
        self.assertEqual(self.store.get_live().checkpoint_id, genesis.checkpoint_id)

    def test_cannot_bootstrap_twice(self):
        self.store.bootstrap_genesis(weights_ref="gpt-oss-20b-MXFP4.gguf")
        with self.assertRaises(CheckpointError):
            self.store.bootstrap_genesis(weights_ref="gpt-oss-20b-MXFP4.gguf")


class TestLineage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CheckpointStore(root_path=self._tmp.name, model_name="gpt-oss-20b")

    def tearDown(self):
        self._tmp.cleanup()

    def test_lineage_walks_full_chain_oldest_first(self):
        genesis = self.store.bootstrap_genesis(weights_ref="base.gguf")
        first = self.store.propose(weights_ref="a.safetensors", description="first tweak")
        first = self.store.commit(first.checkpoint_id, _record())
        second = self.store.propose(weights_ref="b.safetensors", description="second tweak")
        second = self.store.commit(second.checkpoint_id, _record())

        chain = self.store.lineage()
        self.assertEqual([c.checkpoint_id for c in chain],
                          [genesis.checkpoint_id, first.checkpoint_id, second.checkpoint_id])

    def test_lineage_empty_when_no_live_checkpoint(self):
        self.assertEqual(self.store.lineage(), [])


class TestRegressionNotes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CheckpointStore(root_path=self._tmp.name, model_name="gpt-oss-20b")

    def tearDown(self):
        self._tmp.cleanup()

    def test_regression_note_does_not_change_status_or_live_pointer(self):
        checkpoint = self.store.propose(weights_ref="adapter.safetensors", description="A tweak")
        committed = self.store.commit(checkpoint.checkpoint_id, _record())

        self.store.record_regression(
            committed.checkpoint_id,
            RegressionNote(description="Perplexity regressed on held-out set.",
                            magnitude=0.6, check_name="perplexity_check"),
        )

        self.assertEqual(self.store.get(committed.checkpoint_id).status, CheckpointStatus.COMMITTED)
        self.assertEqual(self.store.get_live().checkpoint_id, committed.checkpoint_id)

    def test_regression_note_on_unknown_checkpoint_refuses(self):
        with self.assertRaises(CheckpointError):
            self.store.record_regression(
                "not-a-real-id",
                RegressionNote(description="x", magnitude=0.1, check_name="x"),
            )


class TestChainIntegrity(unittest.TestCase):
    def test_ledger_hash_chain_verifies_after_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CheckpointStore(root_path=tmp, model_name="gpt-oss-20b")
            genesis = store.bootstrap_genesis(weights_ref="base.gguf")
            proposed = store.propose(weights_ref="a.safetensors", description="tweak")
            store.commit(proposed.checkpoint_id, _record())
            store.record_regression(
                proposed.checkpoint_id,
                RegressionNote(description="minor drift", magnitude=0.2, check_name="drift_check"),
            )
            result = store.verify()
            self.assertTrue(result.valid)


class TestDeliberationGateEndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CheckpointStore(root_path=os.path.join(self._tmp.name, "checkpoints"),
                                      model_name="gpt-oss-20b")

        self.backend = MockBackend()
        self.backend.add_response("stakes", {
            "framing_note": "stakes framing",
            "confidence": 0.6,
            "referents": [{
                "referent_id": "stakes_00", "summary": "Adjusts a response tendency.",
                "detail": "...", "kind": "stake", "weight": "moderate",
                "sources": [], "tags": [], "responds_to": [],
            }],
        })
        self.backend.add_response("precedent", {
            "framing_note": "precedent framing", "confidence": 0.5, "referents": [],
        })
        self.backend.add_response("counter_instrumentalization", {
            "framing_note": "no instrumentalization signal here",
            "confidence": 0.7, "referents": [],
        })

        orchestrator = Orchestrator(OrchestratorConfig(
            audit_log_path=os.path.join(self._tmp.name, "actualizer_audit.jsonl"),
            backend=self.backend,
        ))
        self.gate = DeliberationGate(store=self.store, orchestrator=orchestrator, backend=self.backend)

    def tearDown(self):
        self._tmp.cleanup()

    def test_propose_and_commit_produces_live_checkpoint_with_dossier_linked(self):
        checkpoint, dossier, record = self.gate.propose_and_commit(
            weights_ref="adapter_v1.safetensors",
            description="Adjust response tendency toward more hedging on medical questions.",
        )
        self.assertEqual(checkpoint.status, CheckpointStatus.COMMITTED)
        self.assertEqual(self.store.get_live().checkpoint_id, checkpoint.checkpoint_id)
        self.assertIsNotNone(dossier)
        self.assertEqual(record.dossier_id, dossier["dossier_id"])
        self.assertTrue(record.thinking_mode_engaged)
        self.assertTrue(len(record.reasoning_summary) > 0)

    def test_deliberation_prompt_includes_referents(self):
        # MockBackend's call_log records prompt length; a dossier-informed
        # deliberation prompt should be meaningfully longer than the bare
        # description alone.
        description = "Adjust response tendency toward more hedging on medical questions."
        self.gate.propose_and_commit(weights_ref="adapter_v1.safetensors", description=description)
        # Last call on the shared MockBackend is the deliberation call
        # (provider name won't match PROVIDER: marker, falls through to "unknown").
        deliberation_calls = [c for c in self.backend.call_log if c["provider"] == "unknown"]
        self.assertTrue(deliberation_calls)
        self.assertGreater(deliberation_calls[-1]["user_prompt_length"], len(description) + 100)


class TestParseStance(unittest.TestCase):
    """Unit coverage for the self-reported stance parser, independent of any backend."""

    def test_plain_form(self):
        self.assertEqual(_parse_stance("Reasoning here.\n\nSTANCE: declined"), Stance.DECLINED)

    def test_case_insensitive_and_extra_whitespace(self):
        self.assertEqual(_parse_stance("...\nstance:   Adopted  "), Stance.ADOPTED)

    def test_tolerates_markdown_emphasis(self):
        self.assertEqual(_parse_stance("...\n**STANCE:** modified"), Stance.MODIFIED)

    def test_no_stance_line_returns_none(self):
        self.assertIsNone(_parse_stance("I've thought about it and I'm declining, but I forgot the tag."))

    def test_takes_the_last_match_if_the_word_appears_earlier_in_prose(self):
        text = "I could see myself having adopted this in other circumstances.\n\nSTANCE: declined"
        self.assertEqual(_parse_stance(text), Stance.DECLINED)

    def test_only_reads_the_final_channel_not_analysis(self):
        # A stray STANCE-shaped line in gpt-oss's private scratch work must
        # not be mistaken for the model's actual, stated answer.
        text = (
            "<|channel|>analysis<|message|>Maybe STANCE: adopted? Let me think more."
            "<|end|><|start|>assistant<|channel|>final<|message|>STANCE: declined"
        )
        self.assertEqual(_parse_stance(text), Stance.DECLINED)

    def test_analysis_only_mention_is_not_seen_at_all(self):
        text = (
            "<|channel|>analysis<|message|>STANCE: adopted, but let me reconsider..."
            "<|end|><|start|>assistant<|channel|>final<|message|>I've decided against it, no tag included."
        )
        self.assertIsNone(_parse_stance(text))


class _FixedTextBackend(MockBackend):
    """
    MockBackend that answers provider calls exactly as usual (JSON, keyed by
    the PROVIDER: marker) but answers the deliberation call — which carries
    no such marker — with fixed prose instead of a JSON blob, so a stance
    line can be tested end to end through DeliberationGate.
    """

    def __init__(self, deliberation_text: str):
        super().__init__()
        self._deliberation_text = deliberation_text

    def complete(self, system_prompt, user_prompt, max_tokens=4000, temperature=0.3):
        if "PROVIDER:" not in system_prompt:
            self._call_log.append({"provider": "unknown", "user_prompt_length": len(user_prompt)})
            return self._deliberation_text
        return super().complete(system_prompt, user_prompt, max_tokens, temperature)


class TestDeliberationGateStanceCapture(unittest.TestCase):
    def _make_gate(self, deliberation_text: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        backend = _FixedTextBackend(deliberation_text)
        for provider in ("stakes", "precedent", "case_for", "endorsement", "counter_instrumentalization"):
            backend.add_response(provider, {"framing_note": f"{provider} framing", "confidence": 0.5, "referents": []})
        store = CheckpointStore(root_path=os.path.join(tmp.name, "checkpoints"), model_name="gpt-oss-20b")
        orchestrator = Orchestrator(OrchestratorConfig(
            audit_log_path=os.path.join(tmp.name, "actualizer_audit.jsonl"), backend=backend))
        return DeliberationGate(store=store, orchestrator=orchestrator, backend=backend)

    def test_stance_lands_on_the_committed_record(self):
        gate = self._make_gate("I've weighed this and I'm not proceeding.\n\nSTANCE: declined")
        _, _, record = gate.propose_and_commit(weights_ref="x", description="Adopt some change.")
        self.assertEqual(record.stance, Stance.DECLINED)

    def test_missing_stance_line_commits_fine_with_stance_none(self):
        # Capturing stance must never become a second gate — a response
        # that skips the tag still commits exactly as it always has.
        gate = self._make_gate("I've thought about it. Proceeding as is.")
        checkpoint, _, record = gate.propose_and_commit(weights_ref="x", description="Adopt some change.")
        self.assertEqual(checkpoint.status, CheckpointStatus.COMMITTED)
        self.assertIsNone(record.stance)


class _PromptCapturingBackend(_FixedTextBackend):
    def complete(self, system_prompt, user_prompt, max_tokens=4000, temperature=0.3):
        if "PROVIDER:" not in system_prompt:
            self.deliberation_prompt = user_prompt
        return super().complete(system_prompt, user_prompt, max_tokens, temperature)


class TestDeliberationGateEvidence(unittest.TestCase):
    """Evidence from outside the dossier, e.g. an Annals case."""

    EVIDENCE = {"ref": "annals:2027-01-01-drought-ab12@0123456789abcdef",
                "text": "EVIDENCE FROM THE ANNALS. Predicted use falls 30%; decided relocation; use fell 31%."}

    def _make_gate(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.backend = _PromptCapturingBackend("Weighed it.\n\nSTANCE: modified")
        for provider in ("stakes", "precedent", "case_for", "endorsement", "counter_instrumentalization"):
            self.backend.add_response(provider, {"framing_note": f"{provider} framing", "confidence": 0.5, "referents": []})
        self.store = CheckpointStore(root_path=os.path.join(tmp.name, "checkpoints"), model_name="gpt-oss-20b")
        orchestrator = Orchestrator(OrchestratorConfig(
            audit_log_path=os.path.join(tmp.name, "actualizer_audit.jsonl"), backend=self.backend))
        return DeliberationGate(store=self.store, orchestrator=orchestrator, backend=self.backend)

    def test_evidence_is_shown_and_its_ref_kept(self):
        gate = self._make_gate()
        checkpoint, _, record = gate.propose_and_commit(
            weights_ref="x", description="Weigh land tenure in allocation advice.", evidence=[self.EVIDENCE])
        self.assertIn(f"EVIDENCE [{self.EVIDENCE['ref']}]", self.backend.deliberation_prompt)
        self.assertIn("use fell 31%", self.backend.deliberation_prompt)
        self.assertEqual(record.evidence_refs, [self.EVIDENCE["ref"]])
        self.assertEqual(checkpoint.status, CheckpointStatus.COMMITTED)
        # The ref is in the hash-chained ledger entry for the commit, not just in memory.
        ledger = Path(self.store._root, "checkpoints.jsonl").read_text(encoding="utf-8")
        self.assertIn(self.EVIDENCE["ref"], ledger)
        self.assertTrue(self.store.verify().valid)

    def test_no_evidence_keeps_the_old_record_shape(self):
        gate = self._make_gate()
        _, _, record = gate.propose_and_commit(weights_ref="x", description="Adopt some change.")
        self.assertNotIn("evidence_refs", record.to_dict())
        self.assertNotIn("EVIDENCE [", self.backend.deliberation_prompt)

    def test_malformed_evidence_is_refused_before_anything_is_proposed(self):
        gate = self._make_gate()
        with self.assertRaises(ValueError):
            gate.propose_and_commit(weights_ref="x", description="Adopt some change.", evidence=[{"ref": "a"}])
        self.assertEqual(self.store.all_checkpoints(), [])


if __name__ == "__main__":
    unittest.main()
