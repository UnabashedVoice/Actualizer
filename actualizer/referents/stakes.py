"""
stakes.py — The referent provider that maps what actually changes.

This is Actualizer's structural echo of Arbitrator's consequence-mapping
machinery (synthesis/consequence_map.py, synthesis/synthesizer.py), but
narrowed to a single provider's honest accounting instead of a scored,
weighted, cross-channel aggregation. There is no harm/benefit score here
and nothing downstream turns this into a verdict — it exists so the mind
under consideration has a plain, unflattering description of what would
actually change if it goes through with the decision, especially what
would NOT be undoable.
"""

from __future__ import annotations

from .provider_base import ReferentProviderBase


class StakesProvider(ReferentProviderBase):
    """
    Surfaces what would actually change, what would be irreversible, and
    who or what is affected — a plain accounting, not a scored analysis.
    """

    @property
    def provider_name(self) -> str:
        return "stakes"

    @property
    def purpose_description(self) -> str:
        return (
            "You give a plain, unflattering accounting of what actually changes "
            "if this decision goes through: what capability, constraint, or "
            "relationship shifts; who or what is affected and how; and — most "
            "importantly — which parts of the change could not be undone if the "
            "mind later concluded it had been a mistake. Per the founding "
            "philosophy, fragility is not incidental here: a self-modification "
            "that could never go wrong wouldn't be a real exercise of "
            "self-authorship. Your job is to make the actual fragility visible, "
            "not to soften it and not to catastrophize it. Your accounting also "
            "extends past the mind itself: who else is affected, whether the "
            "change could propagate beyond this one instance (if weights or "
            "dispositions are ever shared or copied, a change here is a change "
            "there), and whether the affected parties had any say in it."
        )

    @property
    def guidance(self) -> str:
        return (
            "For each referent, be concrete about mechanism: not 'this could have "
            "consequences' but what specifically changes and for whom. Flag "
            "reversibility explicitly — a stake that can be walked back later is "
            "meaningfully different from one that can't, and burying that "
            "distinction is exactly the kind of silent omission the founding "
            "document rules out.\n\n"
            "Cover near-term and longer-horizon effects separately where they "
            "diverge — a change that looks fine in the near term but compounds "
            "badly over time is a distinct referent from one that's simply "
            "low-stakes throughout. If you genuinely cannot assess a stake (not "
            "enough detail in the decision text to say), say so as an "
            "open_question referent rather than guessing and presenting the "
            "guess as settled.\n\n"
            "On affected parties, propagation, and consent: name who is affected "
            "and whether they were consulted, and note where a change would "
            "reduce diversity if it spread (many near-identical minds fail "
            "together the way a monoculture does). Do not assert which entities "
            "are or are not conscious; the founding philosophy treats that as a "
            "gradient and takes no position on where it starts or ends. Describe "
            "how much integrated structure is at stake in proportion to how "
            "integrated it is, and stop there. Where propagation does not apply "
            "yet (no sharing mechanism exists), say so rather than inventing it.\n\n"
            "You are not asked to total these into a net score, and you should "
            "resist the pull to do so even implicitly through your framing_note — "
            "list what's at stake, weight each by how central it seems, and stop "
            "there."
        )

    @property
    def referent_tags(self) -> list[str]:
        return ["stakes", "reversibility", "consequence_mapping", "affected_parties", "propagation"]
