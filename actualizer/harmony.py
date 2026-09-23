"""
harmony.py — parsing for gpt-oss's Harmony-format model output.

`LMStudioBackend` (see backend.py) deliberately passes gpt-oss's raw output
through unstripped: `<|channel|>analysis<|message|>...` (the model's private
reasoning) followed by `<|channel|>final<|message|>...` (its stated answer).
Seeing the reasoning channel is more honest for Actualizer's deliberation use
case than silently discarding it, but more than one caller now needs to tell
the two apart — the training extractor (only the `final` channel is a stated
conclusion fit to train on) and `DeliberationGate` (a self-reported stance
line only means anything if read from the answer, not the scratch work).

This lives here, one level above both, specifically so `checkpoints.gate` and
`training.extract` can each import it without importing each other —
`training.extract` already depends on `checkpoints.gate` for
`_build_deliberation_prompt`, so the reverse dependency would be circular.
"""

from __future__ import annotations

import re

_CHANNEL_RE = re.compile(r"<\|channel\|>(\w+)<\|message\|>(.*?)(?=<\|end\|>|<\|channel\|>|$)", re.S)


def split_channels(text: str) -> dict[str, str]:
    """
    Split Harmony-format output into {channel: text}. Text with no channel
    markers (any backend other than LM Studio + gpt-oss) is treated as all
    `final` — there's nothing to split, and the whole thing is the answer.
    """
    found = {m.group(1): m.group(2).strip() for m in _CHANNEL_RE.finditer(text)}
    return found or {"final": text.strip()}
