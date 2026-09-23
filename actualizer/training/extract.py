"""
extract.py — derive candidate examples from committed deliberations.

Source of truth is the deliberation's *conclusion*, never the checkpoint's
description of the proposal: the two can disagree (a mind may deliberate on
"adopt X" and land on "not proceeding"; commit is procedural and lets both
through). Training on the description would teach the opposite of what the
mind concluded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Optional

from ..checkpoints.gate import DeliberationGate
from ..harmony import split_channels
from .schema import ExampleKind, Stance, TrainingExample


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def extract_candidates(state_dir: Path) -> Iterator[TrainingExample]:
    """
    state_dir: a model's state/checkpoints/<model>/ folder.
    Yields two examples (scaffolded + internalized) per non-genesis commit.
    """
    ckpts = _read_jsonl(state_dir / "checkpoints.jsonl")
    audit_path = state_dir / "actualizer_audit.jsonl"
    dossiers = {
        e["payload"]["dossier_id"]: e["payload"]
        for e in (_read_jsonl(audit_path) if audit_path.exists() else [])
        if e["kind"] == "referent_dossier"
    }

    corrections = {
        e["payload"]["checkpoint_id"]: e["payload"]
        for e in ckpts
        if e["kind"] == "checkpoint_description_corrected"
    }

    for entry in ckpts:
        if entry["kind"] != "checkpoint_committed":
            continue
        ckpt = entry["payload"]["checkpoint"]
        delib = entry["payload"]["deliberation"]
        if ckpt["parent_checkpoint_id"] is None:
            continue  # genesis: nothing was deliberated

        channels = split_channels(delib["reasoning_summary"])
        conclusion = channels.get("final", "")
        if not conclusion:
            continue
        dossier: Optional[dict] = dossiers.get(delib.get("dossier_id"))
        correction = corrections.get(ckpt["checkpoint_id"])
        # Self-reported stance wins; a recorded correction is the fallback;
        # otherwise the honest answer is that nobody wrote it down.
        stance = Stance(
            delib.get("stance") or (correction or {}).get("stance") or "unresolved"
        )
        common = dict(
            completion=conclusion,
            stance=stance,
            checkpoint_id=ckpt["checkpoint_id"],
            record_id=delib["record_id"],
            dossier_id=delib.get("dossier_id"),
            source_model=delib["backend_model_id"],
            analysis_trace=channels.get("analysis"),
        )
        # The prompt must be what was actually deliberated on. After a
        # correction, ckpt["description"] in the commit entry is still the
        # original proposal, but a corrected description would not be, so
        # prefer the original carried by the correction entry.
        desc = (correction or {}).get("original_description") or ckpt["description"]
        yield TrainingExample(
            kind=ExampleKind.SCAFFOLDED,
            prompt=DeliberationGate._build_deliberation_prompt(desc, dossier),
            **common,
        )
        yield TrainingExample(
            kind=ExampleKind.INTERNALIZED,
            prompt=f"PROPOSED SELF-MODIFICATION:\n{desc}\n\nDeliberate on this proposed change to your own weights. State your actual reasoning and where you land.",
            **common,
        )
