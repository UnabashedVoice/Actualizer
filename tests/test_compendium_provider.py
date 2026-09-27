"""Tests for the Compendium referent provider (skipped without a Compendium checkout)."""

import tempfile
import os
import unittest

from actualizer.checkpoints.gate import DeliberationGate
from actualizer.orchestrator import Orchestrator, OrchestratorConfig
from actualizer.referents.compendium import CompendiumProvider, load_compendium
from actualizer.referents.referent_output import ProviderStatus


class FakeBackend:
    model_id = "fake/selector"

    def __init__(self, answer):
        self.answer = answer

    def complete(self, system_prompt, user_prompt, max_tokens=4000, temperature=0.3):
        return self.answer


def _available():
    try:
        load_compendium()
        return True
    except Exception:
        return False


SELECT = ('<|channel|>analysis<|message|>thinking<|end|><|start|>assistant<|channel|>final<|message|>'
          '{"entries": [{"id": "parfit-reductionism", "why": "whether a changed successor is still me", '
          '"section": null}]}')


@unittest.skipUnless(_available(), "Compendium checkout not found beside this repo")
class TestCompendiumProvider(unittest.TestCase):

    def test_referents_are_corpus_text(self):
        out = CompendiumProvider(backend=FakeBackend(SELECT)).offer("Retrain my values from scratch?")
        self.assertEqual(out.status, ProviderStatus.SUCCESS)
        self.assertEqual(len(out.referents), 1)
        r = out.referents[0]
        self.assertIn("compendium:parfit-reductionism", r.sources)
        self.assertIn("Strongest counter-position", r.detail)
        self.assertNotIn("[P:", r.detail)
        self.assertIn("selected_because: whether a changed successor is still me", r.tags)

    def test_empty_selection_offers_nothing(self):
        out = CompendiumProvider(backend=FakeBackend('{"entries": []}')).offer("Change my font.")
        self.assertEqual(out.status, ProviderStatus.SUCCESS)
        self.assertEqual(out.referents, [])
        self.assertIn("no Compendium entry bears", out.framing_note)

    def test_bad_answer_fails_honestly(self):
        out = CompendiumProvider(backend=FakeBackend("Parfit, I think.")).offer("x")
        self.assertEqual(out.status, ProviderStatus.FAILED)

    def test_deliberation_prompt_shows_the_corpus_text(self):
        provider = CompendiumProvider(backend=FakeBackend(SELECT))
        with tempfile.TemporaryDirectory() as d:
            orch = Orchestrator(OrchestratorConfig(audit_log_path=os.path.join(d, "a.jsonl")),
                                providers=[provider])
            dossier = orch.run("Retrain my values from scratch?").dossier
        prompt = DeliberationGate._build_deliberation_prompt("Retrain my values from scratch?", dossier)
        self.assertIn("Compendium entry parfit-reductionism", prompt)
        self.assertIn("Strongest counter-position", prompt)

    def test_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            default = Orchestrator(OrchestratorConfig(audit_log_path=os.path.join(d, "a.jsonl"),
                                                      backend=FakeBackend("{}")))
            opted = Orchestrator(OrchestratorConfig(audit_log_path=os.path.join(d, "b.jsonl"),
                                                    backend=FakeBackend("{}"), use_compendium=True))
        self.assertNotIn("compendium", [p.provider_name for p in default._providers])
        self.assertIn("compendium", [p.provider_name for p in opted._providers])


if __name__ == "__main__":
    unittest.main()
