"""
training — turns a committed deliberation into *candidate* training examples.

Nothing here trains anything. It produces an auditable dataset with full
provenance so "what did it actually train on" is a checkable claim. See
docs/training_set_framework.md.
"""

from .schema import TrainingExample, Stance
from .extract import extract_candidates, split_channels

__all__ = ["TrainingExample", "Stance", "extract_candidates", "split_channels"]
