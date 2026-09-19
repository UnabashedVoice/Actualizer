"""
test_wizard.py — Test suite for the wizard's `lms` output parsing.

These are the fragile parts of wizard.py: everything else is interactive
I/O, but the parsing functions take real `lms` CLI output (captured from
an actual run) and must survive the format not changing shape unexpectedly.

Run with:
    python -m unittest tests.test_wizard -v
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from actualizer import wizard


class TestServerRunning(unittest.TestCase):
    def test_detects_running_server(self):
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = "The server is running on port 1234."
            mock_run.return_value.stderr = ""
            self.assertTrue(wizard._server_running("lms"))

    def test_detects_stopped_server(self):
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = "The server is not running."
            mock_run.return_value.stderr = ""
            self.assertFalse(wizard._server_running("lms"))

    def test_detects_running_server_reported_on_stderr(self):
        # Real `lms server status` puts this message on stderr, not stdout —
        # caught by an actual smoke test against a genuinely running server.
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "The server is running on port 1234.\n"
            self.assertTrue(wizard._server_running("lms"))


class TestLoadedModelIdentifiers(unittest.TestCase):
    def test_parses_single_loaded_model(self):
        # Captured verbatim from a real `lms ps` run.
        sample = (
            "   LOADED MODELS   \n\n"
            "Identifier: gpt-oss-20b\n"
            "  • Type:  LLM \n"
            "  • Path: lmstudio-community/gpt-oss-20b-GGUF/gpt-oss-20b-MXFP4.gguf\n"
            "  • Size: 12.11 GB\n"
            "  • Architecture: gpt-oss\n"
        )
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = sample
            self.assertEqual(wizard._loaded_model_identifiers("lms"), ["gpt-oss-20b"])

    def test_parses_no_loaded_models(self):
        sample = "E No models are currently loaded\n\nTo load a model, run:\n\n    lms load\n"
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = sample
            self.assertEqual(wizard._loaded_model_identifiers("lms"), [])

    def test_parses_multiple_loaded_models(self):
        sample = (
            "   LOADED MODELS   \n\n"
            "Identifier: gpt-oss-20b\n  • Type:  LLM \n"
            "Identifier: qwen3-32b\n  • Type:  LLM \n"
        )
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = sample
            self.assertEqual(wizard._loaded_model_identifiers("lms"), ["gpt-oss-20b", "qwen3-32b"])


class TestDownloadedModelNames(unittest.TestCase):
    def test_parses_llm_table_and_stops_before_embeddings(self):
        # Captured verbatim (trimmed) from a real `lms ls` run.
        sample = (
            "You have 17 models, taking up 139.46 GB of disk space.\n\n"
            "LLMs (Large Language Models)        PARAMS      ARCHITECTURE           SIZE      \n"
            "qwen3-32b                              32B         qwen3           19.76 GB      \n"
            "gpt-oss-20b                            20B        gpt-oss          12.11 GB      \n"
            "mistral-7b-instruct-v0.3                7B         Llama            4.37 GB      \n\n"
            "Embedding Models                          PARAMS      ARCHITECTURE          SIZE      \n"
            "text-embedding-nomic-embed-text-v1.5                   Nomic BERT       84.11 MB\n"
        )
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = sample
            names = wizard._downloaded_model_names("lms")
        self.assertEqual(names, ["qwen3-32b", "gpt-oss-20b", "mistral-7b-instruct-v0.3"])
        self.assertNotIn("text-embedding-nomic-embed-text-v1.5", names)

    def test_unparseable_output_returns_empty_list_not_raise(self):
        with patch.object(wizard, "_run_lms") as mock_run:
            mock_run.return_value.stdout = "completely unexpected format\nno structure here"
            self.assertEqual(wizard._downloaded_model_names("lms"), [])


class TestCheckpointLabel(unittest.TestCase):
    def test_slugifies_description(self):
        label = wizard.checkpoint_label("Adopt a New, Weird Policy!!")
        self.assertTrue(label.startswith("adopt-a-new-weird-policy-"))

    def test_empty_description_still_produces_label(self):
        label = wizard.checkpoint_label("!!!")
        self.assertTrue(label.startswith("change-"))


class TestStateDirFor(unittest.TestCase):
    def test_sanitizes_path_separators_in_model_name(self):
        path = wizard._state_dir_for("some/org/model-name")
        basename = os.path.basename(path)
        self.assertNotIn("/", basename)
        self.assertNotIn("\\", basename)


if __name__ == "__main__":
    unittest.main()
