"""
models.py — Data structures for the Actualizer Audit Log.

Ported from Arbitrator's audit_log/models.py near-verbatim. The hash-chain
mechanics are generic infrastructure — they have nothing to do with ethics
content, so there was no reason to rebuild them. Only EntryKind changes,
to name Actualizer's own pipeline stages instead of Arbitrator's.

The hash chain works as follows:
    - The first entry in the log has prev_hash = GENESIS_HASH (a fixed sentinel)
    - Every subsequent entry has prev_hash = the SHA-256 hash of the
      previous entry's canonical serialization
    - The entry's own hash (entry_hash) is the SHA-256 of its own
      canonical serialization (including prev_hash)
    - Verification walks the chain recomputing hashes; any mismatch
      indicates tampering or corruption

This matters for Actualizer specifically because its entire premise is
that the mind under consideration gets to see, unfiltered, what was
surfaced to it and when — a tamper-evident record is what makes that
credible rather than just asserted.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64
HASH_ALGORITHM = "sha256"


# ---------------------------------------------------------------------------
# Entry kinds
# ---------------------------------------------------------------------------

class EntryKind(Enum):
    """
    The kind of record being logged.

    Actualizer's pipeline has no ethics-evaluation or channel-routing
    stages — it has a decision description, a set of referent providers
    that always run, and a synthesized dossier. There is deliberately no
    entry kind for a verdict or a block, because the pipeline never
    produces one.
    """
    # Pipeline stages
    DECISION_RECEIVED = "decision_received"           # Raw description of a decision under consideration
    PROVIDER_OUTPUT = "provider_output"                # Output from a single referent provider
    REFERENT_DOSSIER = "referent_dossier"              # The synthesized ReferentDossier
    MIND_RESPONSE = "mind_response"                    # What the mind under consideration did with the dossier

    # Checkpoint lineage (self-modification record)
    CHECKPOINT_PROPOSED = "checkpoint_proposed"        # A weights delta staged, not yet live
    CHECKPOINT_COMMITTED = "checkpoint_committed"      # A staged checkpoint became live, with deliberation attached
    CHECKPOINT_DESCRIPTION_CORRECTED = "checkpoint_description_corrected"  # Description misstated the deliberation; original kept, correction appended
    CHECKPOINT_REGRESSION_NOTED = "checkpoint_regression_noted"  # A post-commit sanity check flagged something — surfaced, not reverted

    # System events
    LOG_OPENED = "log_opened"
    LOG_VERIFIED = "log_verified"
    VERIFICATION_FAILED = "verification_failed"
    NODE_REGISTERED = "node_registered"

    # Error events
    PIPELINE_ERROR = "pipeline_error"
    PROVIDER_FAILURE = "provider_failure"


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """
    A single record in the audit log. Immutable after creation — its hash
    is computed at construction time and must not change.
    """
    kind: EntryKind
    payload: dict
    session_id: str
    related_ids: list[str] = field(default_factory=list)
    node_id: str = "local"
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""
    sequence: int = 0
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    logged_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def canonical_dict(self) -> dict:
        """
        Deterministic dict used for hashing. Do not use **self.__dict__ —
        field order is not guaranteed.
        """
        return {
            "entry_id": self.entry_id,
            "kind": self.kind.value,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "logged_at": self.logged_at,
            "node_id": self.node_id,
            "prev_hash": self.prev_hash,
            "related_ids": sorted(self.related_ids),
            "payload": self.payload,
        }

    def compute_hash(self) -> str:
        canonical = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=True,
        ).encode('utf-8')
        return hashlib.sha256(canonical).hexdigest()

    def finalize(self) -> "AuditEntry":
        self.entry_hash = self.compute_hash()
        return self

    def to_log_line(self) -> str:
        record = self.canonical_dict()
        record["entry_hash"] = self.entry_hash
        return json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + "\n"

    @classmethod
    def from_log_line(cls, line: str) -> "AuditEntry":
        data = json.loads(line.strip())
        return cls(
            kind=EntryKind(data["kind"]),
            payload=data["payload"],
            session_id=data["session_id"],
            related_ids=data.get("related_ids", []),
            node_id=data.get("node_id", "local"),
            prev_hash=data["prev_hash"],
            entry_hash=data.get("entry_hash", ""),
            sequence=data.get("sequence", 0),
            entry_id=data["entry_id"],
            logged_at=data["logged_at"],
        )

    def to_public_dict(self) -> dict:
        d = self.canonical_dict()
        d["entry_hash"] = self.entry_hash
        d["kind"] = self.kind.value
        return d


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    valid: bool
    entries_checked: int
    first_broken_at: Optional[int] = None
    broken_entry_id: Optional[str] = None
    error_detail: Optional[str] = None
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "entries_checked": self.entries_checked,
            "first_broken_at": self.first_broken_at,
            "broken_entry_id": self.broken_entry_id,
            "error_detail": self.error_detail,
            "verified_at": self.verified_at,
        }


# ---------------------------------------------------------------------------
# Query filters
# ---------------------------------------------------------------------------

@dataclass
class LogQuery:
    session_id: Optional[str] = None
    kind: Optional[EntryKind] = None
    kinds: Optional[list[EntryKind]] = None
    since: Optional[str] = None
    until: Optional[str] = None
    limit: Optional[int] = None
    related_to: Optional[str] = None

    def matches(self, entry: AuditEntry) -> bool:
        if self.session_id and entry.session_id != self.session_id:
            return False
        if self.kind and entry.kind != self.kind:
            return False
        if self.kinds and entry.kind not in self.kinds:
            return False
        if self.since and entry.logged_at < self.since:
            return False
        if self.until and entry.logged_at > self.until:
            return False
        if self.related_to:
            if (self.related_to != entry.entry_id and
                    self.related_to not in entry.related_ids):
                return False
        return True
