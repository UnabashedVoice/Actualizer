"""
writers.py — Typed entry constructors for the Actualizer Audit Log.

Adapted from Arbitrator's audit_log/writers.py. Callers never construct
AuditEntry directly — they go through these functions, which keeps
payload shape consistent and entry kinds matched to their payloads.

There is no write_verdict / write_ethics_evaluated equivalent here,
because Actualizer's pipeline never produces a verdict.
"""

from __future__ import annotations

from typing import Optional

from .models import AuditEntry, EntryKind


# ---------------------------------------------------------------------------
# Pipeline stage writers
# ---------------------------------------------------------------------------

def write_decision_received(
    session_id: str,
    raw_input: str,
    decision_id: str,
    source: str = "user",
    node_id: str = "local",
) -> AuditEntry:
    """Log the raw description of a decision a mind is considering about itself."""
    return AuditEntry(
        kind=EntryKind.DECISION_RECEIVED,
        session_id=session_id,
        node_id=node_id,
        related_ids=[decision_id],
        payload={
            "decision_id": decision_id,
            "raw_input": raw_input,
            "source": source,
            "character_count": len(raw_input),
            "word_count": len(raw_input.split()),
        },
    )


def write_provider_output(
    session_id: str,
    provider_output_dict: dict,
    decision_id: str,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log the output of a single referent provider.

    Every provider's raw output goes in the log individually, not just
    the synthesized dossier — the mind under consideration (or anyone
    auditing on its behalf) can see what every provider actually said.
    """
    return AuditEntry(
        kind=EntryKind.PROVIDER_OUTPUT,
        session_id=session_id,
        node_id=node_id,
        related_ids=[decision_id, provider_output_dict.get("output_id", "")],
        payload=provider_output_dict,
    )


def write_referent_dossier(
    session_id: str,
    dossier_dict: dict,
    decision_id: str,
    node_id: str = "local",
) -> AuditEntry:
    """Log the ReferentDossier produced by the DossierSynthesizer."""
    return AuditEntry(
        kind=EntryKind.REFERENT_DOSSIER,
        session_id=session_id,
        node_id=node_id,
        related_ids=[decision_id, dossier_dict.get("dossier_id", "")],
        payload=dossier_dict,
    )


def write_mind_response(
    session_id: str,
    dossier_id: str,
    response_text: str,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log what the mind under consideration did after receiving a dossier —
    its own account of how it weighed the referents and what it decided.

    This is optional and never required: Actualizer does not gate on it,
    and a missing response is not a failure state. When present, it is
    what turns the audit log from "here is what was offered" into "here
    is what was offered and here is how it was actually used" — the
    difference between a referent that was surfaced and one that was
    engaged with.
    """
    return AuditEntry(
        kind=EntryKind.MIND_RESPONSE,
        session_id=session_id,
        node_id=node_id,
        related_ids=[dossier_id],
        payload={
            "dossier_id": dossier_id,
            "response_text": response_text,
        },
    )


# ---------------------------------------------------------------------------
# Checkpoint lineage writers
# ---------------------------------------------------------------------------

def write_checkpoint_proposed(
    session_id: str,
    checkpoint_dict: dict,
    parent_checkpoint_id: Optional[str],
    node_id: str = "local",
) -> AuditEntry:
    """Log a staged (not-yet-live) checkpoint. Never touches the live pointer."""
    related = [checkpoint_dict.get("checkpoint_id", "")]
    if parent_checkpoint_id:
        related.append(parent_checkpoint_id)
    return AuditEntry(
        kind=EntryKind.CHECKPOINT_PROPOSED,
        session_id=session_id,
        node_id=node_id,
        related_ids=related,
        payload=checkpoint_dict,
    )


def write_checkpoint_committed(
    session_id: str,
    checkpoint_dict: dict,
    deliberation_dict: dict,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log a checkpoint becoming live, with the deliberation record that
    justified the write attached in the same entry. A commit with no
    deliberation attached should never reach this writer — see
    checkpoints/store.py:CheckpointStore.commit for where that's enforced.
    """
    return AuditEntry(
        kind=EntryKind.CHECKPOINT_COMMITTED,
        session_id=session_id,
        node_id=node_id,
        related_ids=[
            checkpoint_dict.get("checkpoint_id", ""),
            deliberation_dict.get("dossier_id") or "",
        ],
        payload={
            "checkpoint": checkpoint_dict,
            "deliberation": deliberation_dict,
        },
    )


def write_checkpoint_regression_noted(
    session_id: str,
    checkpoint_id: str,
    regression_dict: dict,
    node_id: str = "local",
) -> AuditEntry:
    """
    Log a post-commit sanity-check finding against a checkpoint. This
    never changes the checkpoint's status or the live pointer — a
    regression is a referent for the next deliberation cycle, not an
    automatic reversal. See checkpoints/store.py for why.
    """
    return AuditEntry(
        kind=EntryKind.CHECKPOINT_REGRESSION_NOTED,
        session_id=session_id,
        node_id=node_id,
        related_ids=[checkpoint_id],
        payload=regression_dict,
    )


# ---------------------------------------------------------------------------
# System event writers
# ---------------------------------------------------------------------------

def write_log_opened(
    session_id: str,
    log_path: str,
    actualizer_version: str = "0.1.0",
    node_id: str = "local",
) -> AuditEntry:
    return AuditEntry(
        kind=EntryKind.LOG_OPENED,
        session_id=session_id,
        node_id=node_id,
        payload={
            "log_path": log_path,
            "actualizer_version": actualizer_version,
            "note": "Audit log initialized. All subsequent entries are hash-chained from this point.",
        },
    )


def write_verification_result(
    session_id: str,
    verification_dict: dict,
    node_id: str = "local",
) -> AuditEntry:
    kind = (
        EntryKind.LOG_VERIFIED
        if verification_dict.get("valid", False)
        else EntryKind.VERIFICATION_FAILED
    )
    return AuditEntry(
        kind=kind,
        session_id=session_id,
        node_id=node_id,
        payload=verification_dict,
    )


def write_pipeline_error(
    session_id: str,
    stage: str,
    error_type: str,
    error_message: str,
    related_ids: Optional[list[str]] = None,
    node_id: str = "local",
) -> AuditEntry:
    return AuditEntry(
        kind=EntryKind.PIPELINE_ERROR,
        session_id=session_id,
        node_id=node_id,
        related_ids=related_ids or [],
        payload={
            "stage": stage,
            "error_type": error_type,
            "error_message": error_message,
        },
    )


def write_provider_failure(
    session_id: str,
    provider_name: str,
    failure_reason: str,
    decision_id: str,
    node_id: str = "local",
) -> AuditEntry:
    return AuditEntry(
        kind=EntryKind.PROVIDER_FAILURE,
        session_id=session_id,
        node_id=node_id,
        related_ids=[decision_id],
        payload={
            "provider_name": provider_name,
            "failure_reason": failure_reason,
            "decision_id": decision_id,
        },
    )
