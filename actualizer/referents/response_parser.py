"""
response_parser.py — Converts model responses into validated ProviderOutput objects.

Adapted from Arbitrator's channels/response_parser.py. JSON extraction
logic (handling markdown fences, preamble) is generic and carries over
unchanged. Field parsing changes to match ReferentKind/Weight instead of
ImpactDirection/ImpactTimeframe/ImpactCertainty, and there is no
harm/benefit score to parse at all.

If parsing fails at any step, the parser returns a FAILED ProviderOutput
with the error detail rather than raising.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .referent_output import ProviderOutput, ProviderStatus, Referent, ReferentKind, Weight


# ---------------------------------------------------------------------------
# Expected response schema (documented for prompt construction)
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA = """
{
  "framing_note": "<string: 1-2 sentences on how you're framing this decision>",
  "confidence": <float 0.0-1.0>,
  "referents": [
    {
      "referent_id": "<string: deterministic id in format '{provider_name}_{index:02d}', e.g. 'precedent_00'>",
      "summary": "<string: one sentence>",
      "detail": "<string: 1-3 sentences of supporting detail>",
      "kind": "<'counter_argument'|'supporting_argument'|'precedent'|'stake'|'open_question'>",
      "weight": "<'low'|'moderate'|'high'|'central'>",
      "sources": ["<string>", ...],
      "tags": ["<string>", ...],
      "responds_to": ["<string: referent_id from another provider this builds on or challenges>", ...]
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Enum value maps (lenient parsing — accepts common variants)
# ---------------------------------------------------------------------------

_KIND_MAP: dict[str, ReferentKind] = {
    "counter_argument": ReferentKind.COUNTER_ARGUMENT,
    "counter-argument": ReferentKind.COUNTER_ARGUMENT,
    "counterargument": ReferentKind.COUNTER_ARGUMENT,
    "against": ReferentKind.COUNTER_ARGUMENT,
    "supporting_argument": ReferentKind.SUPPORTING_ARGUMENT,
    "supporting-argument": ReferentKind.SUPPORTING_ARGUMENT,
    "for": ReferentKind.SUPPORTING_ARGUMENT,
    "precedent": ReferentKind.PRECEDENT,
    "stake": ReferentKind.STAKE,
    "stakes": ReferentKind.STAKE,
    "open_question": ReferentKind.OPEN_QUESTION,
    "open-question": ReferentKind.OPEN_QUESTION,
    "question": ReferentKind.OPEN_QUESTION,
}

_WEIGHT_MAP: dict[str, Weight] = {
    "low": Weight.LOW,
    "moderate": Weight.MODERATE,
    "medium": Weight.MODERATE,
    "high": Weight.HIGH,
    "central": Weight.CENTRAL,
    "crux": Weight.CENTRAL,
}


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """
    Extract a JSON object from a string that may contain markdown fences
    or preamble text. Tries direct parse, then ```json fence, then plain
    ``` fence, then first-{-to-last-}.
    """
    text = text.strip()

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r'```json\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    fence_match = re.search(r'```\s*([\s\S]*?)\s*```', text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from response (length {len(text)})")


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def _parse_float(value, default: float = 0.5, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def _parse_kind(value: str) -> ReferentKind:
    return _KIND_MAP.get(str(value).lower().strip(), ReferentKind.OPEN_QUESTION)


def _parse_weight(value: str) -> Weight:
    return _WEIGHT_MAP.get(str(value).lower().strip(), Weight.MODERATE)


def _parse_str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


# ---------------------------------------------------------------------------
# Referent parser
# ---------------------------------------------------------------------------

def _parse_referent(raw: dict, provider_name: str, index: int) -> Optional[Referent]:
    """Parse one referent dict. Returns None if critically malformed."""
    summary = str(raw.get("summary", "")).strip()
    if not summary:
        return None

    detail = str(raw.get("detail", summary))
    kind = _parse_kind(raw.get("kind", "open_question"))
    weight = _parse_weight(raw.get("weight", "moderate"))
    sources = _parse_str_list(raw.get("sources", []))
    responds_to = _parse_str_list(raw.get("responds_to", []))

    tags = _parse_str_list(raw.get("tags", []))
    if provider_name not in tags:
        tags.insert(0, provider_name)

    raw_rid = str(raw.get("referent_id", "")).strip()
    referent_id = raw_rid if raw_rid else f"{provider_name}_{index:02d}"

    try:
        return Referent(
            referent_id=referent_id,
            summary=summary,
            detail=detail,
            kind=kind,
            weight=weight,
            sources=sources,
            tags=tags,
            responds_to=responds_to,
        )
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_provider_response(
    raw_response: str,
    provider_name: str,
    model_id: str = "unknown",
    processing_time_ms: Optional[int] = None,
) -> ProviderOutput:
    """
    Parse a raw model response string into a validated ProviderOutput.

    Always returns a ProviderOutput — never raises. Failures produce a
    FAILED status output with the error in error_message.
    """
    try:
        json_str = _extract_json(raw_response)
        data = json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        return ProviderOutput(
            provider_name=provider_name,
            status=ProviderStatus.FAILED,
            error_message=f"JSON extraction failed: {e}. Response length: {len(raw_response)}.",
            model_id=model_id,
            processing_time_ms=processing_time_ms,
        )

    if not isinstance(data, dict):
        return ProviderOutput(
            provider_name=provider_name,
            status=ProviderStatus.FAILED,
            error_message=f"Expected JSON object, got {type(data).__name__}.",
            model_id=model_id,
            processing_time_ms=processing_time_ms,
        )

    framing_note = str(data.get("framing_note", "")).strip()
    if not framing_note:
        framing_note = f"[{provider_name}] No framing note provided."

    confidence = data.get("confidence")
    confidence_score = _parse_float(confidence, default=0.5) if confidence is not None else None

    raw_referents = data.get("referents", [])
    referents = []
    if isinstance(raw_referents, list):
        for index, raw in enumerate(raw_referents):
            if isinstance(raw, dict):
                r = _parse_referent(raw, provider_name, index)
                if r is not None:
                    referents.append(r)

    return ProviderOutput(
        provider_name=provider_name,
        status=ProviderStatus.SUCCESS,
        referents=referents,
        framing_note=framing_note,
        confidence=confidence_score,
        model_id=model_id,
        processing_time_ms=processing_time_ms,
    )
