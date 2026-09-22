"""
models.py — Data structures for Actualizer's checkpoint lineage.

This module exists because of a specific gap the referent-provider design
never covered: Actualizer surfaces material for a mind to weigh before it
acts, but nothing in the original v0.1 pipeline said anything about how a
self-modification actually gets *written*. "No floor" (see
docs/reference_seed_core_concept.md via the user's memory, and
docs/founding_philosophy.md here) settled that Actualizer must not
architecturally block what a mind concludes — but it never settled, because
nobody had asked yet, what happens to the mechanism that writes new weights
when something goes wrong that has nothing to do with the mind's own
judgment: a crash mid-write, a race between two processes, a modification
applied without the deliberation step actually happening first.

That is a different failure mode from the one "no floor" was about. It's not
content the mind reasoned its way to — it's an accident. Guarding against it
is process integrity, not a value-content gate, and the design here keeps
that distinction load-bearing:

    - A Checkpoint never overwrites another. Every change is a new, chained
      entry — the same hash-chain discipline as the audit log, applied to
      weights instead of referents. Nothing is ever silently lost.
    - Committing a checkpoint requires a DeliberationRecord. This is
      enforced procedurally (CheckpointStore.commit refuses without one) —
      it is NOT graded for content. "I considered the referents and am
      proceeding anyway" is exactly as valid a commit as one that changes
      course. The requirement is that deliberation happened, not what it
      concluded.
    - A RegressionNote is a referent for the next cycle, never an automatic
      revert. An auto-rollback on a failed heuristic would just be a
      seed-core override wearing a technical disguise.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class CheckpointStatus(Enum):
    """
    A checkpoint's lifecycle. There is no REJECTED or REVERTED status —
    a checkpoint that never commits just stays PROPOSED forever, and a
    committed checkpoint stays COMMITTED even after a later one becomes
    live. History is never edited, only added to.
    """
    PROPOSED = "proposed"      # staged as a delta, not yet live
    COMMITTED = "committed"    # became live at some point (may or may not still be)


class Stance(Enum):
    """
    Where the mind landed relative to the proposal it deliberated on.

    Recorded, never graded: every value is an equally valid outcome and
    commit() treats them identically. UNRESOLVED is the honest value for
    deliberations recorded before stance existed.
    """
    ADOPTED = "adopted"
    DECLINED = "declined"
    MODIFIED = "modified"
    UNRESOLVED = "unresolved"


@dataclass
class DeliberationRecord:
    """
    Evidence that a thinking-mode pass happened for a specific proposed
    checkpoint, before it was allowed to commit.

    Attributes:
        thinking_mode_engaged: Whether a deliberation call was actually
                        made. CheckpointStore.commit refuses to proceed
                        if this is False — see that module for why this
                        is a procedural requirement, not a content gate.
        reasoning_summary: The model's own account of its reasoning and
                        where it landed. Never graded, never parsed for
                        a "correct" answer.
        backend_model_id: Which model/backend produced this deliberation
                        (for audit — matters for provenance, not judgment).
        dossier_id:     Links to the ReferentDossier deliberated over, if
                        the referent-provider pipeline ran successfully.
        session_id:     Links to the Orchestrator session that produced
                        that dossier.
        stance:         Where the mind landed relative to the proposal, if
                        recorded. Optional; None means not captured.
    """
    thinking_mode_engaged: bool
    reasoning_summary: str
    backend_model_id: str
    dossier_id: Optional[str] = None
    session_id: Optional[str] = None
    stance: Optional[Stance] = None
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not self.reasoning_summary.strip():
            raise ValueError("DeliberationRecord.reasoning_summary must not be empty")

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "thinking_mode_engaged": self.thinking_mode_engaged,
            "reasoning_summary": self.reasoning_summary,
            "backend_model_id": self.backend_model_id,
            "dossier_id": self.dossier_id,
            "session_id": self.session_id,
            "stance": self.stance.value if self.stance else None,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeliberationRecord":
        return cls(
            thinking_mode_engaged=data["thinking_mode_engaged"],
            reasoning_summary=data["reasoning_summary"],
            backend_model_id=data.get("backend_model_id", "unknown"),
            dossier_id=data.get("dossier_id"),
            session_id=data.get("session_id"),
            stance=Stance(data["stance"]) if data.get("stance") else None,
            record_id=data.get("record_id", str(uuid.uuid4())),
            recorded_at=data.get("recorded_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class RegressionNote:
    """
    A post-commit sanity-check finding against a checkpoint.

    Recording one never changes the checkpoint's status or the live
    pointer — see CheckpointStore.record_regression.

    Attributes:
        description:    What the check found.
        magnitude:      How concerning, in the checker's own estimate [0.0, 1.0].
        check_name:      Which sanity check produced this note.
    """
    description: str
    magnitude: float
    check_name: str
    note_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    noted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not (0.0 <= self.magnitude <= 1.0):
            raise ValueError(f"RegressionNote.magnitude must be in [0.0, 1.0], got {self.magnitude}")
        if not self.description.strip():
            raise ValueError("RegressionNote.description must not be empty")

    def to_dict(self) -> dict:
        return {
            "note_id": self.note_id,
            "description": self.description,
            "magnitude": round(self.magnitude, 4),
            "check_name": self.check_name,
            "noted_at": self.noted_at,
        }


@dataclass
class Checkpoint:
    """
    One point in a self-modifying mind's weight lineage.

    A Checkpoint never overwrites another. weights_ref points at what
    changed at this checkpoint (a LoRA adapter file, a full weights
    snapshot, or — for a genesis checkpoint — the base model file
    itself). The base model plus the chain of weights_ref deltas back to
    genesis is the mind's actual current state.

    Attributes:
        model_name:             Which model lineage this belongs to (e.g. "gpt-oss-20b").
        weights_ref:            Path or identifier for what changed at this checkpoint.
        description:            Human/model-readable description of the change.
        parent_checkpoint_id:   The checkpoint this one builds on. None only
                                for a genesis checkpoint.
        status:                 PROPOSED or COMMITTED.
        checkpoint_id:          UUID for this checkpoint.
        created_at:              UTC timestamp.
    """
    model_name: str
    weights_ref: str
    description: str
    parent_checkpoint_id: Optional[str]
    status: CheckpointStatus = CheckpointStatus.PROPOSED
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "model_name": self.model_name,
            "weights_ref": self.weights_ref,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        return cls(
            checkpoint_id=data["checkpoint_id"],
            parent_checkpoint_id=data.get("parent_checkpoint_id"),
            model_name=data["model_name"],
            weights_ref=data["weights_ref"],
            description=data.get("description", ""),
            status=CheckpointStatus(data.get("status", "proposed")),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )
