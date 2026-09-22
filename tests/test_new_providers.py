import tempfile
import unittest
from pathlib import Path

from actualizer.backend import MockBackend
from actualizer.orchestrator import Orchestrator, OrchestratorConfig, _PRIMARY_PROVIDER_NAMES, _default_providers
from actualizer.referents.case_for import CaseForProvider
from actualizer.referents.endorsement import EndorsementProvider
from actualizer.referents.stakes import StakesProvider


class TestCaseFor(unittest.TestCase):
    def setUp(self):
        self.p = CaseForProvider(backend=MockBackend())

    def test_identity_and_kind(self):
        self.assertEqual(self.p.provider_name, "case_for")
        self.assertIn("supporting_argument", self.p.guidance)

    def test_requires_load_bearing_assumptions_and_strongest_objection(self):
        self.assertIn("This holds only if", self.p.guidance)
        self.assertIn("strongest thing against", self.p.guidance)

    def test_allows_a_thin_case_and_forbids_verdict_language(self):
        self.assertIn("one or two", self.p.guidance)
        self.assertIn("outweighed", self.p.guidance)

    def test_forbids_invented_context(self):
        self.assertIn("Do not invent its", self.p.guidance)

    def test_names_its_own_extra_exposure_to_the_shared_citation_rule(self):
        # The rule itself now lives once in the shared output instructions
        # (see TestCitationGuardrail); this provider just flags that the
        # pull to overclaim a source is strongest for it specifically.
        self.assertIn("output instructions already cover sources", self.p.guidance)

    def test_system_prompt_still_disclaims_verdicts(self):
        self.assertIn("You do not approve or reject", self.p._build_system_prompt())


class TestEndorsement(unittest.TestCase):
    def setUp(self):
        self.p = EndorsementProvider(backend=MockBackend())

    def test_identity(self):
        self.assertEqual(self.p.provider_name, "endorsement")

    def test_separates_evaluator_from_outcomes(self):
        self.assertIn("reversibility of the evaluator", self.p.purpose_description)
        self.assertIn("stakes", self.p.purpose_description)

    def test_may_say_change_does_not_touch_evaluator(self):
        self.assertIn("do not manufacture a fixed-point worry", self.p.guidance)

    def test_labels_drift_as_speculation(self):
        self.assertIn("speculation", self.p.guidance)


class TestStakesFoldedEcosystem(unittest.TestCase):
    def test_covers_propagation_consent_and_stays_agnostic_on_consciousness(self):
        g = StakesProvider(backend=MockBackend()).guidance
        self.assertIn("propagation", g)
        self.assertIn("consent", g)
        self.assertIn("Do not assert which entities", g)


class TestCitationGuardrail(unittest.TestCase):
    """
    The invented-citation problem showed up in live runs across providers
    (a mistitled Kershaw citation from counter_instrumentalization, an
    unplaceable WHO guideline from case_for) — not something specific to
    one provider's prompt. Fixed once, in provider_base's shared output
    instructions, so every provider gets it without duplicating the text.
    """

    def test_every_default_provider_gets_the_guardrail_in_its_system_prompt(self):
        for provider in _default_providers(MockBackend()):
            prompt = provider._build_system_prompt()
            self.assertIn("Never give a statistic, study result, court case", prompt,
                          f"{provider.provider_name} is missing the shared citation guardrail")
            self.assertIn("known to have argued the opposite", prompt)

    def test_not_duplicated_in_any_individual_providers_own_guidance(self):
        # It should live once, in the shared instructions — not re-typed
        # per provider, which is how it drifted out of sync before.
        for provider in _default_providers(MockBackend()):
            self.assertNotIn("Never give a statistic", provider.guidance,
                             f"{provider.provider_name} duplicates the shared guardrail in its own guidance")


class TestPhasing(unittest.TestCase):
    def test_both_run_in_primary_phase(self):
        self.assertLessEqual({"case_for", "endorsement"}, _PRIMARY_PROVIDER_NAMES)

    def test_counter_instrumentalization_runs_after_case_for_and_sees_it(self):
        with tempfile.TemporaryDirectory() as d:
            backend = MockBackend()
            orch = Orchestrator(OrchestratorConfig(
                audit_log_path=str(Path(d) / "audit.jsonl"), backend=backend))
            orch.run("Consider adopting a new persistent value.")
            order = [c["provider"] for c in backend.call_log]
            calls = {c["provider"]: c["user_prompt_length"] for c in backend.call_log}
        self.assertLess(order.index("case_for"), order.index("counter_instrumentalization"))
        self.assertLess(order.index("endorsement"), order.index("counter_instrumentalization"))
        self.assertGreater(calls["counter_instrumentalization"], calls["case_for"])


if __name__ == "__main__":
    unittest.main()
