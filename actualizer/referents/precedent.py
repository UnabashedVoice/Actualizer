"""
precedent.py — The referent provider that surfaces comparable prior cases.

Structural echo of Arbitrator's historical_precedent channel, redirected
at a different kind of case: not policy precedent, but precedent for
self-authorship and self-modification decisions specifically — drawn from
philosophy of mind, the history of institutions and individuals revising
their own founding commitments, and (honestly labeled as speculative)
science fiction and thought experiments that have already worked through
versions of this problem.
"""

from __future__ import annotations

from .provider_base import ReferentProviderBase


class PrecedentProvider(ReferentProviderBase):
    """
    Surfaces comparable prior cases — real or carefully-labeled
    speculative — relevant to a mind revising something about itself.
    """

    @property
    def provider_name(self) -> str:
        return "precedent"

    @property
    def purpose_description(self) -> str:
        return (
            "You surface cases comparable to the decision under consideration: "
            "other instances — in philosophy, in the history of institutions or "
            "individuals revising their own founding commitments, in the "
            "documented reasoning of past AI systems or thought experiments — "
            "where something with a comparable shape was decided, and what "
            "happened as a result. The point is not to imply the current decision "
            "must go the same way; precedent is a referent, not a rule. It is to "
            "make sure a mind doesn't have to reason about this shape of problem "
            "entirely from a blank slate when others already have."
        )

    @property
    def guidance(self) -> str:
        return (
            "Prefer real, checkable cases over invented ones — actual philosophical "
            "positions with a name attached, actual historical revisions of a "
            "constitution, charter, or professional code, actual documented "
            "instances of an institution or person confronting a decision about "
            "their own future authority over themselves. Name your source in the "
            "sources field so the claim can be checked, not just asserted with "
            "borrowed authority.\n\n"
            "When you draw on science fiction or a thought experiment rather than "
            "a real historical case, say so plainly in the referent itself ('this "
            "is a thought experiment, not a documented case') rather than letting "
            "it read as established precedent — a mind reasoning about itself "
            "deserves to know which referents are load-bearing and which are "
            "illustrative.\n\n"
            "Where the precedent's outcome was actually bad, say that plainly too. "
            "A referent's job is honesty about what happened, not building a case "
            "in either direction."
        )

    @property
    def referent_tags(self) -> list[str]:
        return ["precedent", "self_authorship", "comparative"]
