"""
test_audit_log.py — Test suite for the Actualizer Audit Log.

Run with:
    python -m unittest tests.test_audit_log -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from actualizer.audit_log import AuditLog, EntryKind, GENESIS_HASH, LogQuery, writers


class TestAuditLogAppend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmp.name) / "audit.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_entry_chains_to_genesis(self):
        log = AuditLog(path=self.log_path, auto_open=False)
        entry = writers.write_decision_received(
            session_id="s1", raw_input="Consider X", decision_id="d1",
        )
        appended = log.append(entry)
        self.assertEqual(appended.sequence, 0)
        self.assertEqual(appended.prev_hash, GENESIS_HASH)
        self.assertTrue(appended.entry_hash)

    def test_second_entry_chains_to_first(self):
        log = AuditLog(path=self.log_path, auto_open=False)
        e1 = log.append(writers.write_decision_received(
            session_id="s1", raw_input="Consider X", decision_id="d1",
        ))
        e2 = log.append(writers.write_provider_output(
            session_id="s1", provider_output_dict={"output_id": "o1"}, decision_id="d1",
        ))
        self.assertEqual(e2.prev_hash, e1.entry_hash)
        self.assertEqual(e2.sequence, 1)

    def test_auto_open_writes_log_opened_entry(self):
        log = AuditLog(path=self.log_path, auto_open=True)
        entries = list(log.read_all())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, EntryKind.LOG_OPENED)


class TestAuditLogVerification(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmp.name) / "audit.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _seed_log(self) -> AuditLog:
        log = AuditLog(path=self.log_path, auto_open=False)
        log.append(writers.write_decision_received(
            session_id="s1", raw_input="Consider X", decision_id="d1",
        ))
        log.append(writers.write_referent_dossier(
            session_id="s1", dossier_dict={"dossier_id": "dos1"}, decision_id="d1",
        ))
        return log

    def test_verify_valid_chain(self):
        log = self._seed_log()
        result = log.verify(log_verification=False)
        self.assertTrue(result.valid)
        self.assertEqual(result.entries_checked, 2)

    def test_verify_detects_tampering(self):
        self._seed_log()

        # Tamper: rewrite the first line's payload without recomputing the hash
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        import json
        first = json.loads(lines[0])
        first["payload"]["raw_input"] = "Consider something else entirely"
        lines[0] = json.dumps(first)
        self.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        log = AuditLog(path=self.log_path, auto_open=False)
        result = log.verify(log_verification=False)
        self.assertFalse(result.valid)
        self.assertEqual(result.first_broken_at, 0)


class TestAuditLogQuery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmp.name) / "audit.jsonl"
        self.log = AuditLog(path=self.log_path, auto_open=False)
        self.log.append(writers.write_decision_received(
            session_id="s1", raw_input="A", decision_id="d1",
        ))
        self.log.append(writers.write_decision_received(
            session_id="s2", raw_input="B", decision_id="d2",
        ))

    def tearDown(self):
        self._tmp.cleanup()

    def test_query_by_session(self):
        results = self.log.query(LogQuery(session_id="s1"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].session_id, "s1")

    def test_get_session(self):
        results = self.log.get_session("s2")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].payload["raw_input"], "B")


if __name__ == "__main__":
    unittest.main()
