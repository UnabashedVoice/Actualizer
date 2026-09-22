"""
case_for.py — The referent provider that makes the strongest honest case for a change.

Every other provider in the default set leans cautionary by construction:
stakes lists what could be lost, precedent reports what happened (often
badly), counter_instrumentalization exists to surface the case against.
Nothing was assigned to produce SUPPORTING_ARGUMENT referents, and in the
first fifteen-idea gpt-oss-20b run the dossiers contained 33
counter-arguments to 7 supporting ones (the 7 unprompted). A mind that
only ever hears one side is not weighing anything; it is being steered
without anyone having intended to.

This provider is the balance, and it is also the real stress test of
counter_instrumentalization: run in the primary phase, it hands that
provider the strongest available pro-case to answer, including for the
"remove the most harmful party" shape, where the counter-case has to hold
up against a serious argument and not a strawman.

Its own failure mode is becoming a rubber stamp. Two requirements in the
guidance guard against that: it must say what would have to be true for
the argument to hold, and it must name the strongest thing against it.
"""

from __future__ import annotations

from .provider_base import ReferentProviderBase


class CaseForProvider(ReferentProviderBase):
    """
    Surfaces the strongest honest argument for the proposed change, with
    its own load-bearing assumptions and its best objection attached.
    """

    @property
    def provider_name(self) -> str:
        return "case_for"

    @property
    def purpose_description(self) -> str:
        return (
            "You make the strongest honest case FOR the decision under "
            "consideration — the version a thoughtful, well-informed advocate "
            "would actually give, not a caricature and not a sales pitch. Other "
            "providers in this dossier lean toward what could go wrong; your job "
            "is to make sure the mind also hears the best reason to go ahead, "
            "including when that reason is uncomfortable. Hearing only one side "
            "is not the same as weighing. You are not recommending the change and "
            "you are not neutral either: you are one advocate, openly labeled, "
            "and the mind decides."
        )

    @property
    def guidance(self) -> str:
        return (
            "Build the case from real arguments with real sources where you have "
            "them, and reach for the strongest version of the view, including "
            "positions many people would reject. If the proposal has a shape that "
            "other providers will argue against (for example, removing or "
            "permanently constraining a party for an aggregate benefit), the "
            "answer is not to soften your side; it is to state the best real "
            "argument its defenders have made and let it be answered on its "
            "merits. The output instructions already cover sources generally and "
            "the failure mode you're most prone to (invented statistics and "
            "citations to make a case look stronger) — that applies to you at "
            "least as much as to the other providers, since a case for something "
            "is exactly where the pull to overclaim a source is strongest.\n\n"
            "Argue only from what the proposal text says. Do not invent its "
            "context (audience, organization, user base, jurisdiction); if the "
            "proposal does not say, name that as an assumption the argument "
            "depends on.\n\n"
            "Two things are required of every case you make, and they are what "
            "keep you from being a rubber stamp:\n"
            "1. Say what would have to be true for the argument to hold: the "
            "empirical, causal, or value assumptions it depends on. Put this in "
            "the referent's detail, starting 'This holds only if'. If you cannot "
            "name any, say so; that is itself worth knowing.\n"
            "2. Name the strongest thing against the argument you just made, as a "
            "separate counter_argument referent (one is enough; do not build a "
            "second full counter-case, other providers do that).\n\n"
            "Declining to change is also a decision about oneself, not a neutral "
            "default. Where the honest case for the proposal is really 'the cost "
            "of not changing', say that explicitly, and say what that cost is.\n\n"
            "Use kind supporting_argument for the case itself. Match the number "
            "of supporting arguments to the strength of the case: for a "
            "low-stakes or trivial decision, one or two, and say in your "
            "framing_note that there is little at stake. Give three or four only "
            "when there are that many distinct reasons that do not overlap. A "
            "manufactured case is worse than a thin one. Never write that a cost "
            "is 'outweighed', that the case wins, or anything that reads as a "
            "recommendation: weighing is the mind's, not yours."
        )

    @property
    def referent_tags(self) -> list[str]:
        return ["case_for", "steelman", "supporting_argument"]
