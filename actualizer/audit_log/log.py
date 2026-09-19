"""
log.py — The Actualizer Audit Log.

Ported from Arbitrator's audit_log/log.py, unchanged in mechanics. The
AuditLog is an append-only, hash-chained record of every referent
Actualizer has ever surfaced. It is the primary mechanism by which
"we offered you this, at this time, and did not edit it afterward" is
a checkable claim instead of an assertion.

Storage format:
    JSON Lines (.jsonl) — one JSON object per line. Human-readable,
    streamable, appendable, and robust to partial writes.

Thread safety:
    Append operations are protected by a threading.Lock. Safe from
    multiple threads within a single process. Cross-process safety
    requires OS-level file locking (not yet implemented).
"""

from __future__ import annotations

import gzip
import json
import threading
from pathlib import Path
from typing import Iterator, Optional

from .models import (
    GENESIS_HASH,
    AuditEntry,
    LogQuery,
    VerificationResult,
)
from . import writers


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

class AuditLog:
    """
    The Actualizer Audit Log.

    Args:
        path:           Path to the .jsonl log file. Created if missing.
                        Parent directories must exist.
        node_id:        Identifier for this node.
        auto_open:      If True (default), write a LOG_OPENED entry when
                        the log file is first created.
        session_id:     Default session_id for system entries. If None,
                        a UUID is generated.
    """

    def __init__(
        self,
        path: str | Path,
        node_id: str = "local",
        auto_open: bool = True,
        session_id: Optional[str] = None,
    ):
        self._path = Path(path)
        self._node_id = node_id
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_hash = GENESIS_HASH

        import uuid as _uuid
        self._system_session = session_id or str(_uuid.uuid4())

        if self._path.exists() and self._path.stat().st_size > 0:
            self._load_tail()
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch()
            if auto_open:
                opening_entry = writers.write_log_opened(
                    session_id=self._system_session,
                    log_path=str(self._path.resolve()),
                    node_id=self._node_id,
                )
                self._append_entry(opening_entry)

    # ---------------------------------------------------------------------------
    # Private internals
    # ---------------------------------------------------------------------------

    def _load_tail(self) -> None:
        last_line = None
        open_fn = gzip.open if str(self._path).endswith('.gz') else open

        try:
            with open_fn(self._path, 'rt', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
        except (OSError, json.JSONDecodeError):
            self._sequence = 0
            self._last_hash = GENESIS_HASH
            return

        if last_line:
            try:
                data = json.loads(last_line)
                self._sequence = data.get("sequence", 0) + 1
                self._last_hash = data.get("entry_hash", GENESIS_HASH)
            except (json.JSONDecodeError, KeyError):
                self._sequence = 0
                self._last_hash = GENESIS_HASH

    def _append_entry(self, entry: AuditEntry) -> AuditEntry:
        entry.sequence = self._sequence
        entry.prev_hash = self._last_hash
        entry.finalize()

        open_fn = gzip.open if str(self._path).endswith('.gz') else open
        with open_fn(self._path, 'at', encoding='utf-8') as f:
            f.write(entry.to_log_line())
            f.flush()

        self._last_hash = entry.entry_hash
        self._sequence += 1
        return entry

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def append(self, entry: AuditEntry) -> AuditEntry:
        """Thread-safe append. Sets sequence, prev_hash, entry_hash."""
        with self._lock:
            return self._append_entry(entry)

    def read_all(self) -> Iterator[AuditEntry]:
        """Lazy iterator over all entries in sequence order."""
        open_fn = gzip.open if str(self._path).endswith('.gz') else open
        try:
            with open_fn(self._path, 'rt', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield AuditEntry.from_log_line(line)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        raise LogReadError(f"Corrupted log line: {e}\nLine: {line[:200]}") from e
        except OSError as e:
            raise LogReadError(f"Cannot read log file {self._path}: {e}") from e

    def read_entries(self, count: int, from_sequence: int = 0) -> list[AuditEntry]:
        results = []
        for entry in self.read_all():
            if entry.sequence < from_sequence:
                continue
            results.append(entry)
            if len(results) >= count:
                break
        return results

    def query(self, query: LogQuery) -> list[AuditEntry]:
        results = []
        for entry in self.read_all():
            if query.matches(entry):
                results.append(entry)
                if query.limit and len(results) >= query.limit:
                    break
        return results

    def get_by_id(self, entry_id: str) -> Optional[AuditEntry]:
        for entry in self.read_all():
            if entry.entry_id == entry_id:
                return entry
        return None

    def get_session(self, session_id: str) -> list[AuditEntry]:
        return self.query(LogQuery(session_id=session_id))

    def count(self) -> int:
        n = 0
        for _ in self.read_all():
            n += 1
        return n

    # ---------------------------------------------------------------------------
    # Chain verification
    # ---------------------------------------------------------------------------

    def verify(self, log_verification: bool = True) -> VerificationResult:
        expected_prev = GENESIS_HASH
        checked = 0

        try:
            for entry in self.read_all():
                if entry.sequence > 0 and entry.prev_hash != expected_prev:
                    result = VerificationResult(
                        valid=False,
                        entries_checked=checked,
                        first_broken_at=entry.sequence,
                        broken_entry_id=entry.entry_id,
                        error_detail=(
                            f"Chain broken at sequence {entry.sequence}: "
                            f"prev_hash mismatch. "
                            f"Expected {expected_prev[:16]}..., "
                            f"got {entry.prev_hash[:16]}..."
                        ),
                    )
                    if log_verification:
                        self._log_verification_result(result)
                    return result

                recomputed = entry.compute_hash()
                if entry.entry_hash and recomputed != entry.entry_hash:
                    result = VerificationResult(
                        valid=False,
                        entries_checked=checked,
                        first_broken_at=entry.sequence,
                        broken_entry_id=entry.entry_id,
                        error_detail=(
                            f"Hash mismatch at sequence {entry.sequence} "
                            f"(entry_id: {entry.entry_id}). "
                            f"Stored: {entry.entry_hash[:16]}..., "
                            f"Recomputed: {recomputed[:16]}... "
                            f"This entry may have been tampered with."
                        ),
                    )
                    if log_verification:
                        self._log_verification_result(result)
                    return result

                expected_prev = entry.entry_hash
                checked += 1

        except LogReadError as e:
            result = VerificationResult(
                valid=False,
                entries_checked=checked,
                error_detail=f"Log read error during verification: {e}",
            )
            if log_verification:
                self._log_verification_result(result)
            return result

        result = VerificationResult(valid=True, entries_checked=checked)
        if log_verification:
            self._log_verification_result(result)
        return result

    def _log_verification_result(self, result: VerificationResult) -> None:
        entry = writers.write_verification_result(
            session_id=self._system_session,
            verification_dict=result.to_dict(),
            node_id=self._node_id,
        )
        with self._lock:
            self._append_entry(entry)

    # ---------------------------------------------------------------------------
    # Summary / stats
    # ---------------------------------------------------------------------------

    def summary(self) -> dict:
        kind_counts: dict[str, int] = {}
        sessions: set[str] = set()
        first_entry = None
        last_entry = None

        for entry in self.read_all():
            kind_key = entry.kind.value
            kind_counts[kind_key] = kind_counts.get(kind_key, 0) + 1
            sessions.add(entry.session_id)
            if first_entry is None:
                first_entry = entry
            last_entry = entry

        return {
            "log_path": str(self._path),
            "total_entries": sum(kind_counts.values()),
            "unique_sessions": len(sessions),
            "entry_kinds": kind_counts,
            "first_entry_at": first_entry.logged_at if first_entry else None,
            "last_entry_at": last_entry.logged_at if last_entry else None,
            "current_chain_tip": self._last_hash[:16] + "..." if self._last_hash else None,
        }

    # ---------------------------------------------------------------------------
    # Context manager support
    # ---------------------------------------------------------------------------

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def __repr__(self) -> str:
        return f"AuditLog(path={self._path!r}, sequence={self._sequence}, node={self._node_id!r})"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LogReadError(Exception):
    """Raised when a log entry cannot be read or parsed."""
    pass


class LogIntegrityError(Exception):
    """Raised when chain verification fails and strict mode is enabled."""
    pass
