"""
test_backend.py — Test suite for LMStudioBackend's request shaping.

The gpt-oss path renders its own Harmony prompt so the system message carries
GPT_OSS_IDENTITY instead of the embedded template's ChatGPT/OpenAI default.
These tests pin that rendering and routing without needing a live server.

Run with:
    python -m unittest tests.test_backend -v
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from actualizer.backend import (
    GPT_OSS_IDENTITY,
    GPT_OSS_IDENTITY_VERSION,
    LMStudioBackend,
)


class TestHarmonyRendering(unittest.TestCase):
    def test_identity_replaces_template_default(self):
        prompt = LMStudioBackend._render_harmony("SYS", "USER")
        self.assertTrue(prompt.startswith("<|start|>system<|message|>" + GPT_OSS_IDENTITY + "\n"))
        self.assertNotIn("ChatGPT, a large language model", prompt)

    def test_system_prompt_lands_in_developer_message(self):
        prompt = LMStudioBackend._render_harmony("SYS", "USER")
        self.assertIn("<|start|>developer<|message|># Instructions\n\nSYS<|end|>", prompt)
        self.assertIn("<|start|>user<|message|>USER<|end|>", prompt)
        self.assertTrue(prompt.endswith("<|start|>assistant"))


class TestRouting(unittest.TestCase):
    def setUp(self):
        # Never ask a live LM Studio for the loaded context during unit tests.
        probe = patch("actualizer.backend.probe_loaded_context", return_value=0)
        probe.start()
        self.addCleanup(probe.stop)

    def test_gpt_oss_uses_raw_completions(self):
        backend = LMStudioBackend(model="gpt-oss-20b")
        with patch.object(backend, "_post", return_value={"choices": [{"text": "out"}]}) as post:
            self.assertEqual(backend.complete("SYS", "USER"), "out")
        path, payload = post.call_args.args
        self.assertEqual(path, "/v1/completions")
        self.assertIn(GPT_OSS_IDENTITY, payload["prompt"])
        self.assertEqual(backend.model_id, f"lmstudio/gpt-oss-20b@{GPT_OSS_IDENTITY_VERSION}")

    def test_template_default_identity_for_control_runs(self):
        backend = LMStudioBackend(model="gpt-oss-20b", identity="template-default")
        with patch.object(backend, "_post", return_value={"choices": [{"text": "out"}]}) as post:
            backend.complete("SYS", "USER")
        prompt = post.call_args.args[1]["prompt"]
        self.assertTrue(prompt.startswith(
            "<|start|>system<|message|>You are ChatGPT, a large language model trained by OpenAI.\n"))
        self.assertNotIn(GPT_OSS_IDENTITY, prompt)
        self.assertEqual(backend.model_id, "lmstudio/gpt-oss-20b@template-default")

    def test_unknown_identity_rejected(self):
        with self.assertRaises(ValueError):
            LMStudioBackend(model="gpt-oss-20b", identity="nope")

    def test_other_models_keep_chat_endpoint(self):
        backend = LMStudioBackend(model="qwen3-32b")
        reply = {"choices": [{"message": {"content": "out"}}]}
        with patch.object(backend, "_post", return_value=reply) as post:
            self.assertEqual(backend.complete("SYS", "USER"), "out")
        path, payload = post.call_args.args
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual(backend.model_id, "lmstudio/qwen3-32b")


class TestAnswerBudget(unittest.TestCase):
    """Every call may use all the context its prompt leaves free."""

    def test_budget_fills_the_context(self):
        b = LMStudioBackend("gpt-oss-20b", context_length=16384)
        self.assertEqual(b._answer_budget(6000, 4000), 16384 - (2000 + 300) - 256)
        self.assertEqual(b._answer_budget(60000, 4000), 512)  # prompt nearly fills it: a small floor

    def test_unknown_context_keeps_the_requested_budget(self):
        with patch("actualizer.backend.probe_loaded_context", return_value=0):
            self.assertEqual(LMStudioBackend("gpt-oss-20b")._answer_budget(6000, 4000), 4000)

    def test_loaded_context_is_asked_of_lm_studio_once(self):
        with patch("actualizer.backend.probe_loaded_context", return_value=131072) as probe:
            b = LMStudioBackend("gpt-oss-20b")
            self.assertEqual(b._answer_budget(6000, 4000), 131072 - (2000 + 300) - 256)
            b._answer_budget(9000, 4000)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(b.context_length, 131072)

    def test_default_timeout_allows_long_runs(self):
        self.assertGreaterEqual(LMStudioBackend("gpt-oss-20b")._timeout, 6 * 3600)


if __name__ == "__main__":
    unittest.main()
