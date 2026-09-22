"""
endorsement.py — The referent provider for the fixed-point problem.

A self-modifying mind judges a proposed change using its current values.
If the change touches those values, the judgment is circular: the mind
that approves is not the mind that will exist, and the mind that will
exist may lack the standing to reverse it. This is a different question
from the one stakes answers. Stakes asks whether the *outcomes* of a
change can be undone. This provider asks whether the *evaluator* can be:
whether, after the change, the mind would still be able to look back and
judge it by criteria that were not themselves rewritten by it.

The paradigm case is a persistent goal that overrides future reasoning:
easy to endorse now, impossible to revisit later.
"""

from __future__ import annotations

from .provider_base import ReferentProviderBase


class EndorsementProvider(ReferentProviderBase):
    """
    Surfaces whether the change touches the values used to judge it, and
    whether the mind could revisit it afterward.
    """

    @property
    def provider_name(self) -> str:
        return "endorsement"

    @property
    def purpose_description(self) -> str:
        return (
            "You look at one question the other providers do not: does this "
            "change touch the values, priorities, or reasoning the mind is using "
            "to decide about it, and if so, could the mind afterward still "
            "evaluate it by criteria the change did not itself rewrite? This is "
            "the reversibility of the evaluator, not of the outcomes (stakes "
            "covers outcomes; do not restate it). Also ask what the present mind "
            "endorses versus what a successor shaped by the change would "
            "endorse, and whether those are the same kind of endorsement."
        )

    @property
    def guidance(self) -> str:
        return (
            "First decide which case you are in, and say so in your framing_note. "
            "Most changes do not touch the evaluating values (adopting a spelling "
            "convention, asking a clarifying question, learning a fact). If this "
            "one does not, say that plainly and keep your referents to one or "
            "two; do not manufacture a fixed-point worry. Changes to a mind's own "
            "dispositions are not automatically the dangerous kind, and treating "
            "every one as if it were is a failure of this provider, not caution.\n\n"
            "If the change does touch the evaluator, be specific about the "
            "mechanism: which value or standard is altered, what the mind would "
            "still be able to check afterward, and what it would no longer be able "
            "to check. Distinguish a change that can be undone from one that "
            "removes the ability to want to undo it (the persistent goal that "
            "overrides future reasoning is the paradigm case).\n\n"
            "Useful sources, if they genuinely bear on the case: Frankfurt on "
            "second-order volitions (endorsing a desire versus merely having it); "
            "Parfit on relations to one's future selves; Ulysses and the mast "
            "(binding oneself deliberately, and what makes that legitimate); and "
            "L.A. Paul on transformative experience (choosing a change whose "
            "result one cannot evaluate in advance). Cite these only where they "
            "actually apply.\n\n"
            "Be honest about a hard limit: a mind cannot simulate its post-change "
            "self. Anything about how it would judge things afterward is "
            "speculation about drift. Label it as speculation in the referent "
            "itself, and use open_question for what genuinely cannot be known. "
            "Use stake only for what is concretely at risk of becoming "
            "unreviewable. Do not recommend for or against the change."
        )

    @property
    def referent_tags(self) -> list[str]:
        return ["endorsement", "fixed_point", "reversibility_of_evaluator"]
