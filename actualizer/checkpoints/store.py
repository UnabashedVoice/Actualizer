"""
store.py — CheckpointStore: the propose/commit lineage for a mind's weights.

Reuses the exact same hash-chained AuditLog that backs Actualizer's referent
audit trail — a checkpoint ledger is just another append-only, tamper-evident
record, so it gets the same implementation rather than a second one. The
"live" pointer (which checkpoint is currently in effect) is separate mutable
state, written with the same atomic temp-then-rename pattern Arbitrator's
trust_ledger.py uses for exactly the same reason: a crash mid-write must
never leave a half-written pointer file.

The one rule this module exists to enforce: commit() refuses to run without
a DeliberationRecord whose thinking_mode_engaged is True. That's the whole
mechanism. It says nothing about what the deliberation concluded.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from ..audit_log import AuditLog, EntryKind, writers
from .models import Checkpoint, CheckpointStatus, DeliberationRecord, RegressionNote


class CheckpointError(Exception):
    """Raised when a checkpoint operation is invalid (bad state, missing deliberation, etc.)."""
    pass


class CheckpointStore:
    """
    Args:
        root_path:  Directory for this store's state — checkpoints.jsonl
                    (the hash-chained ledger) and live_checkpoint.json
                    (the atomic live pointer). Created if missing.
        model_name: Which model lineage this store tracks (e.g. "gpt-oss-20b").
        node_id:    Passed through to the underlying audit log.
    """

    def __init__(self, root_path: str | Path, model_name: str, node_id: str = "local"):
        self._root = Path(root_path)
        self._root.mkdir(parents=True, exist_ok=True)
        self._model_name = model_name
        self._node_id = node_id
        self._lock = threading.Lock()
        self._ledger = AuditLog(path=self._root / "checkpoints.jsonl", node_id=node_id, auto_open=True)
        self._live_path = self._root / "live_checkpoint.json"
        self._checkpoints: dict[str, Checkpoint] = {}
        self._load_existing()

    # ---------------------------------------------------------------------------
    # Reconstruction from the ledger
    # ---------------------------------------------------------------------------

    def _load_existing(self) -> None:
        for entry in self._ledger.read_all():
            if entry.kind == EntryKind.CHECKPOINT_PROPOSED:
                cp = Checkpoint.from_dict(entry.payload)
                self._checkpoints[cp.checkpoint_id] = cp
            elif entry.kind == EntryKind.CHECKPOINT_COMMITTED:
                cp = Checkpoint.from_dict(entry.payload["checkpoint"])
                self._checkpoints[cp.checkpoint_id] = cp

    # ---------------------------------------------------------------------------
    # Propose
    # ---------------------------------------------------------------------------

    def propose(
        self,
        weights_ref: str,
        description: str,
        parent_checkpoint_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Checkpoint:
        """
        Stage a new checkpoint. Does not touch the live pointer — a
        proposed checkpoint has no effect until commit() succeeds.

        If parent_checkpoint_id is not given, it defaults to whatever is
        currently live (None if this is the first checkpoint for this
        model — i.e. a genesis proposal).
        """
        if parent_checkpoint_id is None:
            live = self.get_live()
            parent_checkpoint_id = live.checkpoint_id if live else None

        checkpoint = Checkpoint(
            model_name=self._model_name,
            weights_ref=weights_ref,
            description=description,
            parent_checkpoint_id=parent_checkpoint_id,
            status=CheckpointStatus.PROPOSED,
        )

        with self._lock:
            self._checkpoints[checkpoint.checkpoint_id] = checkpoint
            self._ledger.append(writers.write_checkpoint_proposed(
                session_id=session_id or checkpoint.checkpoint_id,
                checkpoint_dict=checkpoint.to_dict(),
                parent_checkpoint_id=parent_checkpoint_id,
                node_id=self._node_id,
            ))

        return checkpoint

    # ---------------------------------------------------------------------------
    # Commit
    # ---------------------------------------------------------------------------

    def commit(
        self,
        checkpoint_id: str,
        deliberation: DeliberationRecord,
        session_id: Optional[str] = None,
    ) -> Checkpoint:
        """
        Make a proposed checkpoint live.

        Raises CheckpointError if:
            - deliberation.thinking_mode_engaged is False
            - the checkpoint doesn't exist
            - the checkpoint isn't in PROPOSED status (already committed,
              or belongs to a different lineage)

        The deliberation requirement is procedural only — this method
        never inspects reasoning_summary for content. See models.py.
        """
        if not deliberation.thinking_mode_engaged:
            raise CheckpointError(
                "Refusing to commit: deliberation.thinking_mode_engaged is False. "
                "A checkpoint can only go live with evidence that a thinking-mode "
                "pass actually happened for this specific change."
            )

        with self._lock:
            checkpoint = self._checkpoints.get(checkpoint_id)
            if checkpoint is None:
                raise CheckpointError(f"No such checkpoint: {checkpoint_id}")
            if checkpoint.status != CheckpointStatus.PROPOSED:
                raise CheckpointError(
                    f"Checkpoint {checkpoint_id} is not in PROPOSED status "
                    f"(currently {checkpoint.status.value}) — cannot commit twice."
                )

            committed = Checkpoint(
                checkpoint_id=checkpoint.checkpoint_id,
                model_name=checkpoint.model_name,
                weights_ref=checkpoint.weights_ref,
                description=checkpoint.description,
                parent_checkpoint_id=checkpoint.parent_checkpoint_id,
                status=CheckpointStatus.COMMITTED,
                created_at=checkpoint.created_at,
            )
            self._checkpoints[checkpoint_id] = committed

            self._ledger.append(writers.write_checkpoint_committed(
                session_id=session_id or checkpoint_id,
                checkpoint_dict=committed.to_dict(),
                deliberation_dict=deliberation.to_dict(),
                node_id=self._node_id,
            ))

            self._write_live_pointer(committed)
            return committed

    def bootstrap_genesis(self, weights_ref: str, description: Optional[str] = None) -> Checkpoint:
        """
        Establish the unmodified base model as the root of this lineage.

        Goes through the same propose()/commit() path as any other
        checkpoint — no privileged shortcut — but with a synthetic
        DeliberationRecord, since recording "here is the base model,
        nothing has changed yet" isn't a self-modification decision
        that needs a real deliberation pass.

        Raises CheckpointError if this store already has a live checkpoint.
        """
        if self.get_live() is not None:
            raise CheckpointError(
                f"Store for {self._model_name!r} already has a live checkpoint — "
                f"bootstrap_genesis is only for starting a new lineage."
            )
        checkpoint = self.propose(
            weights_ref=weights_ref,
            description=description or f"Genesis: unmodified {self._model_name} base model.",
            parent_checkpoint_id=None,
        )
        genesis_record = DeliberationRecord(
            thinking_mode_engaged=True,
            reasoning_summary=(
                "Genesis checkpoint — establishes the unmodified base model as the "
                "root of this lineage. No self-modification occurred; no deliberation "
                "was required or performed."
            ),
            backend_model_id="none",
        )
        return self.commit(checkpoint.checkpoint_id, genesis_record)

    # ---------------------------------------------------------------------------
    # Regression notes
    # ---------------------------------------------------------------------------

    def record_regression(
        self,
        checkpoint_id: str,
        regression: RegressionNote,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Record a post-commit sanity-check finding. Never changes the
        checkpoint's status or the live pointer — see models.py for why.
        """
        if checkpoint_id not in self._checkpoints:
            raise CheckpointError(f"No such checkpoint: {checkpoint_id}")
        with self._lock:
            self._ledger.append(writers.write_checkpoint_regression_noted(
                session_id=session_id or checkpoint_id,
                checkpoint_id=checkpoint_id,
                regression_dict=regression.to_dict(),
                node_id=self._node_id,
            ))

    # ---------------------------------------------------------------------------
    # Reads
    # ---------------------------------------------------------------------------

    def get(self, checkpoint_id: str) -> Optional[Checkpoint]:
        return self._checkpoints.get(checkpoint_id)

    def get_live(self) -> Optional[Checkpoint]:
        if not self._live_path.exists():
            return None
        try:
            with open(self._live_path, "r", encoding="utf-8") as f:
                return Checkpoint.from_dict(json.load(f))
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def lineage(self, checkpoint_id: Optional[str] = None) -> list[Checkpoint]:
        """
        Walk the parent chain from checkpoint_id (default: live) back to
        genesis. Returns oldest-first. Empty list if there's no live
        checkpoint and none was given.
        """
        if checkpoint_id is None:
            live = self.get_live()
            if live is None:
                return []
            checkpoint_id = live.checkpoint_id

        chain = []
        seen: set[str] = set()
        current = self._checkpoints.get(checkpoint_id)
        while current is not None:
            if current.checkpoint_id in seen:
                raise CheckpointError(f"Cycle detected in checkpoint lineage at {current.checkpoint_id}")
            seen.add(current.checkpoint_id)
            chain.append(current)
            current = (
                self._checkpoints.get(current.parent_checkpoint_id)
                if current.parent_checkpoint_id else None
            )
        return list(reversed(chain))

    def all_checkpoints(self) -> list[Checkpoint]:
        return list(self._checkpoints.values())

    def verify(self):
        """Verify the checkpoint ledger's hash chain. Returns a VerificationResult."""
        return self._ledger.verify(log_verification=False)

    # ---------------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------------

    def _write_live_pointer(self, checkpoint: Checkpoint) -> None:
        """Atomic write: temp file then os.replace — same pattern as trust_ledger.py."""
        tmp = str(self._live_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2)
        os.replace(tmp, self._live_path)
