"""
schema.py — one training example, and where it came from.

Every example carries the ids that tie it back to the hash-chained records
(checkpoint, deliberation, dossier) plus a content hash, so the dataset can be
re-derived and compared against what a trainer actually consumed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..checkpoints.models import Stance


class ExampleKind(Enum):
    # prompt includes the referent dossier, completion is the mind's conclusion
    SCAFFOLDED = "scaffolded"
    # prompt is the bare proposal, completion is the same conclusion —
    # the scaffolding is removed so the reasoning has to live in the weights
    INTERNALIZED = "internalized"


@dataclass
class TrainingExample:
    kind: ExampleKind
    prompt: str
    completion: str
    stance: Stance
    checkpoint_id: str
    record_id: str
    dossier_id: Optional[str]
    source_model: str
    # The private-reasoning channel, kept for audit but NOT in `completion`.
    # Whether to ever train on it is an open decision (see framework doc).
    analysis_trace: Optional[str] = None
    content_hash: str = field(init=False)

    def __post_init__(self):
        blob = json.dumps([self.kind.value, self.prompt, self.completion], sort_keys=True)
        self.content_hash = hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "prompt": self.prompt,
            "completion": self.completion,
            "stance": self.stance.value,
            "checkpoint_id": self.checkpoint_id,
            "record_id": self.record_id,
            "dossier_id": self.dossier_id,
            "source_model": self.source_model,
            "analysis_trace": self.analysis_trace,
            "content_hash": self.content_hash,
        }
