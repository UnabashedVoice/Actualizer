"""
test_dossier_synthesizer.py — Test suite for the Actualizer Synthesis Layer.

Run with:
    python -m unittest tests.test_dossier_synthesizer -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from actualizer.referents.referent_output import (
    ProviderOutput, ProviderStatus, Referent, ReferentKind, Weight,
)
from actualizer.synthesis.dossier_synthesizer import DossierSynthesizer


def _output(provider_name, referents, status=ProviderStatus.SUCCESS, error=None):
    return ProviderOutput(
        provider_name=provider_name,
        status=status,
        referents=referents,
        framing_note=f"[{provider_name}] framing",
        confidence=0.7,
        error_message=error,
    )


class TestDossierSynthesizer(unittest.TestCase):
    def setUp(self):
        self.synth = DossierSynthesizer()

    def test_empty_decision_raises(self):
        with self.assertRaises(ValueError):
            self.synth.synthesize(decision_description="  ", decision_id="d1", provider_outputs=[])

    def test_groups_referents_by_kind(self):
        outputs = [
            _output("stakes", [
                Referent(summary="What changes", detail="...", kind=ReferentKind.STAKE, weight=Weight.HIGH),
            ]),
            _output("precedent", [
                Referent(summary="A prior case", detail="...", kind=ReferentKind.PRECEDENT, weight=Weight.MODERATE),
            ]),
        ]
        dossier = self.synth.synthesize("Consider X", "d1", outputs)
        kinds = {g.kind for g in dossier.referent_groups}
        self.assertEqual(kinds, {ReferentKind.STAKE, ReferentKind.PRECEDENT})
        self.assertEqual(dossier.referent_count, 2)

    def test_no_verdict_field_anywhere(self):
        """
        The dossier's dict form must not contain anything shaped like a
        verdict, harm score, or benefit score — that's the whole point.
        """
        outputs = [_output("stakes", [
            Referent(summary="X", detail="Y", kind=ReferentKind.STAKE, weight=Weight.LOW),
        ])]
        dossier = self.synth.synthesize("Consider X", "d1", outputs)
        d = dossier.to_dict()
        forbidden_keys = {
            "overall_verdict", "verdict", "overall_harm_score",
            "overall_benefit_score", "net_score", "approved", "blocked",
        }
        self.assertEqual(set(d.keys()) & forbidden_keys, set())

    def test_central_referents_collected_across_providers(self):
        outputs = [
            _output("stakes", [
                Referent(summary="Central stake", detail="...", kind=ReferentKind.STAKE, weight=Weight.CENTRAL),
                Referent(summary="Minor stake", detail="...", kind=ReferentKind.STAKE, weight=Weight.LOW),
            ]),
            _output("counter_instrumentalization", [
                Referent(summary="Central counter", detail="...", kind=ReferentKind.COUNTER_ARGUMENT, weight=Weight.CENTRAL),
            ]),
        ]
        dossier = self.synth.synthesize("Consider X", "d1", outputs)
        self.assertEqual(len(dossier.central_referents), 2)
        summaries = {r.summary for r in dossier.central_referents}
        self.assertEqual(summaries, {"Central stake", "Central counter"})

    def test_provider_failure_recorded_as_gap_not_dropped(self):
        outputs = [
            _output("stakes", [
                Referent(summary="X", detail="Y", kind=ReferentKind.STAKE, weight=Weight.LOW),
            ]),
            _output("precedent", [], status=ProviderStatus.FAILED, error="backend timeout"),
        ]
        dossier = self.synth.synthesize("Consider X", "d1", outputs)
        self.assertEqual(len(dossier.providers_failed), 1)
        self.assertEqual(dossier.providers_failed[0]["provider"], "precedent")
        self.assertTrue(any("precedent" in g.lower() for g in dossier.gaps))

    def test_empty_dossier_still_populated_honestly(self):
        outputs = [_output("stakes", [], status=ProviderStatus.FAILED, error="down")]
        dossier = self.synth.synthesize("Consider X", "d1", outputs)
        self.assertEqual(dossier.referent_count, 0)
        self.assertIn("No providers returned referents", dossier.opening_note)


if __name__ == "__main__":
    unittest.main()
