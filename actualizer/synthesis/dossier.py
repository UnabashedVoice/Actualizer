"""
dossier.py — The ReferentDossier produced by the Synthesis Layer.

This is the Actualizer analogue of Arbitrator's consequence_map.py, and
the clearest place the two projects' data models diverge. ConsequenceMap
carries overall_verdict, overall_harm_score, overall_benefit_score, and
net_score — fields that exist because something downstream (a human
decision-maker, in Arbitrator's case) is meant to read a number and act.
ReferentDossier has none of those fields. There is nothing to sum,
nothing to gate on, and nothing that resolves to pass/fail. What survives
from Arbitrator's design principles is the discipline underneath the
scoring, not the scoring itself:

    - Every section is populated even if its content is "nothing here."
      Silent omissions are not permitted.
    - Provider failures are always surfaced, never silently dropped.
    - The dossier is not a recommendation and not an evaluation. It is a
      collection of things worth reckoning with, assembled honestly.
    - The full dossier is published to the audit log, verbatim.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..referents.referent_output import Referent, ReferentKind


@dataclass
class ReferentGroup:
    """All referents of a single kind, gathered across every provider."""
    kind: ReferentKind
    referents: list[Referent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "referents": [r.to_dict() for r in self.referents],
        }


@dataclass
class ProviderFraming:
    """One provider's own framing note and self-reported confidence."""
    provider_name: str
    framing_note: str
    confidence: Optional[float]

    def to_dict(self) -> dict:
        return {
            "provider_name": self.provider_name,
            "framing_note": self.framing_note,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
        }


@dataclass
class ReferentDossier:
    """
    The complete referent dossier — the primary output of the Synthesis
    Layer, handed to the mind under consideration (and logged verbatim
    to the audit record).

    Attributes:
        decision_description:  The original decision text.
        decision_id:            Links to the DECISION_RECEIVED audit entry.

        opening_note:           A short, plain-language orientation —
                                what was asked, what was found. Not a
                                verdict; there is nothing to conclude.
        referent_groups:        All referents, grouped by kind.
        central_referents:      Referents any provider marked CENTRAL,
                                surfaced together regardless of kind —
                                these are the closest-to-the-crux items
                                across all perspectives.
        provider_framings:      Each succeeding provider's own framing note.

        provider_outputs:       The raw provider outputs (for audit).
        providers_invoked:      Which providers were called.
        providers_succeeded:    Which providers returned SUCCESS.
        providers_failed:       Which providers failed (with reasons).
        gaps:                   Explicitly documented gaps in the dossier.

        dossier_id:             UUID for this dossier.
        generated_at:           UTC timestamp.
    """
    decision_description: str
    decision_id: str

    opening_note: str
    referent_groups: list[ReferentGroup] = field(default_factory=list)
    central_referents: list[Referent] = field(default_factory=list)
    provider_framings: list[ProviderFraming] = field(default_factory=list)

    provider_outputs: list[dict] = field(default_factory=list)
    providers_invoked: list[str] = field(default_factory=list)
    providers_succeeded: list[str] = field(default_factory=list)
    providers_failed: list[dict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    dossier_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def all_referents(self) -> list[Referent]:
        referents = []
        for group in self.referent_groups:
            referents.extend(group.referents)
        return referents

    @property
    def referent_count(self) -> int:
        return len(self.all_referents)

    def to_dict(self) -> dict:
        return {
            "dossier_id": self.dossier_id,
            "generated_at": self.generated_at,
            "decision_description": self.decision_description,
            "decision_id": self.decision_id,

            "opening_note": self.opening_note,
            "referent_groups": [g.to_dict() for g in self.referent_groups],
            "central_referents": [r.to_dict() for r in self.central_referents],
            "provider_framings": [pf.to_dict() for pf in self.provider_framings],

            "providers_invoked": self.providers_invoked,
            "providers_succeeded": self.providers_succeeded,
            "providers_failed": self.providers_failed,
            "gaps": self.gaps,

            "provider_outputs": self.provider_outputs,
        }
