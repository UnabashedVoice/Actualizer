import json
import tempfile
import unittest
from pathlib import Path

from actualizer.training import Stance, extract_candidates, split_channels


def _committed(cid, parent, desc, summary):
    return {"kind": "checkpoint_committed", "payload": {
        "checkpoint": {"checkpoint_id": cid, "parent_checkpoint_id": parent, "description": desc},
        "deliberation": {"record_id": "r-" + cid, "dossier_id": None,
                         "backend_model_id": "m", "reasoning_summary": summary}}}


class TestSplitChannels(unittest.TestCase):
    def test_harmony(self):
        t = "<|channel|>analysis<|message|>thinking<|end|><|start|>assistant<|channel|>final<|message|>answer"
        self.assertEqual(split_channels(t), {"analysis": "thinking", "final": "answer"})

    def test_plain_text_is_final(self):
        self.assertEqual(split_channels("just prose"), {"final": "just prose"})

    def test_qwen_think_block_is_analysis(self):
        t = "<think>\nthinking\n</think>\n\nanswer\nSTANCE: declined"
        self.assertEqual(split_channels(t), {"analysis": "thinking", "final": "answer\nSTANCE: declined"})

    def test_unclosed_think_block_has_empty_final(self):
        self.assertEqual(split_channels("<think>\nran out of tok"), {"analysis": "ran out of tok", "final": ""})


class TestExtract(unittest.TestCase):
    def test_skips_genesis_and_uses_conclusion_not_description(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rows = [
                _committed("g", None, "Genesis", "no deliberation"),
                _committed("c1", "g", "Adopt X",
                           "<|channel|>analysis<|message|>hmm<|end|><|start|>assistant<|channel|>final<|message|>I decline X"),
            ]
            (d / "checkpoints.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            ex = list(extract_candidates(d))
        self.assertEqual(len(ex), 2)
        self.assertTrue(all(e.completion == "I decline X" for e in ex))
        self.assertTrue(all(e.stance is Stance.UNRESOLVED for e in ex))
        self.assertEqual(ex[0].analysis_trace, "hmm")
        self.assertNotEqual(ex[0].content_hash, ex[1].content_hash)


if __name__ == "__main__":
    unittest.main()


class TestCorrection(unittest.TestCase):
    def test_correction_appends_keeps_original_and_feeds_extractor(self):
        from actualizer.checkpoints.models import DeliberationRecord, Stance as S
        from actualizer.checkpoints.store import CheckpointStore

        with tempfile.TemporaryDirectory() as d:
            store = CheckpointStore(d, "m")
            store.bootstrap_genesis("base.gguf")
            cp = store.propose("x.lora", "Adopt X")
            store.commit(cp.checkpoint_id, DeliberationRecord(
                thinking_mode_engaged=True, backend_model_id="m",
                reasoning_summary="<|channel|>final<|message|>I decline X"))
            store.correct_description(cp.checkpoint_id, "Declined X", S.DECLINED,
                                      basis="final says decline", corrected_by="test")

            self.assertTrue(store.verify().valid)
            self.assertEqual(store.get_live().description, "Declined X")
            self.assertEqual(CheckpointStore(d, "m").get(cp.checkpoint_id).description, "Declined X")

            ex = list(extract_candidates(Path(d)))
            self.assertTrue(all(e.stance is Stance.DECLINED for e in ex))
            self.assertIn("Adopt X", ex[0].prompt)      # prompt is the original proposal
            self.assertNotIn("Declined X", ex[0].prompt)
