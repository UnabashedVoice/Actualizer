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

Qwen3 (and other thinking models served through LM Studio's chat endpoint)
put their private reasoning inline instead, as a leading `<think>...</think>`
block. That is mapped onto the same `analysis`/`final` split so callers don't
need to care which model produced the text.
"""

from __future__ import annotations

import re

_CHANNEL_RE = re.compile(r"<\|channel\|>(\w+)<\|message\|>(.*?)(?=<\|end\|>|<\|channel\|>|$)", re.S)
_THINK_RE = re.compile(r"^\s*<think>(.*?)(?:</think>|$)(.*)", re.S)


def split_channels(text: str) -> dict[str, str]:
    """
    Split model output into {channel: text}: Harmony channel markers
    (gpt-oss), or a leading <think> block (Qwen3) as `analysis` with the rest
    as `final`. A <think> block that never closes — the response ran out of
    tokens mid-thought — is all `analysis` with an empty `final`, so a
    truncated response can't pass its scratch work off as an answer. Text
    with neither is treated as all `final`: there's nothing to split, and the
    whole thing is the answer.
    """
    found = {m.group(1): m.group(2).strip() for m in _CHANNEL_RE.finditer(text)}
    if found:
        return found
    think = _THINK_RE.match(text)
    if think:
        return {"analysis": think.group(1).strip(), "final": think.group(2).strip()}
    return {"final": text.strip()}
