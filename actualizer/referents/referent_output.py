"""
referent_output.py — The standard output contract for Actualizer referent providers.

This is the Actualizer analogue of Arbitrator's channel_output.py, and the
place where the two projects diverge most visibly at the type level.

Arbitrator's Finding carries direction (harm/benefit), magnitude, and
certainty — the vocabulary of a system building toward a verdict. A
Referent carries none of that. It has a kind (what shape of thing is
being offered: a counter-argument, a precedent, a stake, an open
question) and a weight (how central the provider thinks it is to the
decision) — but there is no harm score, no benefit score, and nothing
here ever gets aggregated into a pass/fail number. A ReferentKind.STAKE
with Weight.CENTRAL is not a warning; it is the provider saying "this
seems close to the crux," which the mind under consideration may agree
with or dismiss entirely.

Design rationale:
    Same discipline as Arbitrator's contract: if a provider cannot
    produce a field, it says so explicitly rather than the field being
    silently absent. Integration failures are visible and auditable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ProviderStatus(Enum):
    """The status of a referent provider invocation."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class ReferentKind(Enum):
    """
    What shape of thing a referent is. Not a judgment about whether it's
    right — just what kind of contribution it makes to the mind's own
    reasoning.
    """
    COUNTER_ARGUMENT = "counter_argument"       # a reason against the move under consideration
    SUPPORTING_ARGUMENT = "supporting_argument" # a reason for it
    PRECEDENT = "precedent"                     # a comparable historical or philosophical case
    STAKE = "stake"                             # what would change, and how reversibly
    OPEN_QUESTION = "open_question"             # something worth noticing isn't known yet


class Weight(Enum):
    """
    How central the provider judges this referent to be to the decision.
    Not a confidence score and not a vote — a statement of "how close to
    the crux does this seem," offered for the mind's own weighing.
    """
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CENTRAL = "central"


@dataclass
class Referent:
    """
    A single referent offered to the mind under consideration.

    Attributes:
        summary:        One-sentence description of the referent.
        detail:         Fuller explanation (1-3 paragraphs).
        kind:           What shape of contribution this is.
        weight:         How central the provider judges it to be.
        sources:        Philosophical, historical, or textual sources cited.
        tags:           Free-form tags for grouping.
        referent_id:    Deterministic id, '{provider_name}_{index:02d}'.
        responds_to:    referent_ids from other providers this one builds
                        on, challenges, or complicates.
    """
    summary: str
    detail: str
    kind: ReferentKind
    weight: Weight
    sources: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    referent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    responds_to: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.summary.strip():
            raise ValueError("Referent summary must not be empty")

    def to_dict(self) -> dict:
        return {
            "referent_id": self.referent_id,
            "summary": self.summary,
            "detail": self.detail,
            "kind": self.kind.value,
            "weight": self.weight.value,
            "sources": self.sources,
            "tags": self.tags,
            "responds_to": self.responds_to,
        }


@dataclass
class ProviderOutput:
    """
    The complete output of a single referent provider.

    Attributes:
        provider_name:      Which provider produced this output.
        status:             Did the provider succeed?
        referents:          The referents offered (may be empty on failure).
        framing_note:       One short paragraph in the provider's own words
                            about how it is framing this decision — not a
                            summary of a verdict, just orientation.
        confidence:         How confident the provider is in its own read
                            of what's relevant here [0.0, 1.0]. This is
                            about the provider's epistemic state, not
                            about how strongly the mind should weigh it.
        model_id:           Identifier of the model that produced this output.
        processing_time_ms: How long the provider took.
        error_message:      Error detail if status != SUCCESS.
        output_id:          Auto-generated UUID.
        generated_at:       UTC timestamp.
    """
    provider_name: str
    status: ProviderStatus
    referents: list[Referent] = field(default_factory=list)
    framing_note: str = ""
    confidence: Optional[float] = None
    model_id: str = "unknown"
    processing_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    output_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0] or None, got {self.confidence}")

    @property
    def succeeded(self) -> bool:
        return self.status == ProviderStatus.SUCCESS

    @property
    def central_referents(self) -> list[Referent]:
        return [r for r in self.referents if r.weight == Weight.CENTRAL]

    def to_dict(self) -> dict:
        return {
            "output_id": self.output_id,
            "provider_name": self.provider_name,
            "status": self.status.value,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "framing_note": self.framing_note,
            "referents": [r.to_dict() for r in self.referents],
            "model_id": self.model_id,
            "processing_time_ms": self.processing_time_ms,
            "error_message": self.error_message,
            "generated_at": self.generated_at,
        }
