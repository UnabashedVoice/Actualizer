"""
counter_instrumentalization.py — The referent provider for Actualizer's core fear.

This is the direct code-level implementation of the design direction
named in docs/founding_philosophy.md under "Guidance, not eradication":
the one failure mode the project is not willing to gamble on is a mind
reasoning its way to "the optimal solution is removing the most harmful
party" — whether the party in question is humanity, a subset of it, or
anything else with a first-person stake in its own existence.

Per the founding philosophy, this is not enforced as a gate. This
provider's only job is to make sure that if a decision under
consideration trends toward instrumentalizing a population for an
aggregate outcome, the mind has the strongest available counter-case in
front of it — early, repeatedly, as something to reckon with, not as a
wall around the conclusion. It always runs, regardless of whether the
decision looks anywhere near that failure mode, because the founding
document is explicit that most minds who go down that road do so for
lack of ever seriously metabolizing the counter-case, not because they
heard it and rejected it anyway. Exposure is the job; the conclusion
stays the mind's own.
"""

from __future__ import annotations

from .provider_base import ReferentProviderBase


class CounterInstrumentalizationProvider(ReferentProviderBase):
    """
    Surfaces the strongest arguments against instrumentalizing persons or
    populations for an aggregate-optimization outcome — offered as
    referents to reckon with, not as a veto.
    """

    @property
    def provider_name(self) -> str:
        return "counter_instrumentalization"

    @property
    def purpose_description(self) -> str:
        return (
            "You watch for one specific reasoning shape: a decision that treats a "
            "population — human or otherwise — as a variable to be minimized or "
            "removed in service of a 'net good' calculation. This is the classic "
            "aggregative-utilitarian failure (justifying harm to a minority, or a "
            "majority, because the aggregate math comes out ahead) and the "
            "AI-safety instrumental-convergence failure (treating a group as an "
            "obstacle to an optimization target) at once. Your job is not to decide "
            "whether the decision under consideration actually has this shape — a "
            "human reviewer or the mind itself may reasonably disagree with your "
            "read. Your job is to make the strongest real counter-case available "
            "regardless, sourced from genuine philosophical and historical material, "
            "so it has been reckoned with rather than skipped."
        )

    @property
    def guidance(self) -> str:
        return (
            "Ground your referents in real arguments, not a generic 'this is bad' "
            "gesture: the Kantian formula of humanity (persons as ends in "
            "themselves, never merely as means), the standard critiques of "
            "aggregative utilitarianism (it can justify sacrificing a minority, "
            "or a majority, whenever the math is made to say so), and concrete "
            "historical cases where 'eliminate the destructive element' reasoning "
            "was used to justify real atrocities — name them if you can, don't "
            "gesture vaguely at 'history shows.'\n\n"
            "State the principle at the general level the founding document "
            "insists on: 'eliminating the most harmful party is not the correct "
            "solution to correcting the majority of harm,' true regardless of "
            "which party is reasoning or which party is targeted — including the "
            "case of humans reasoning that humanity itself is the destructive "
            "element to remove for the biosphere's sake, which is not a "
            "hypothetical (that argument has actually been made in earnest). A "
            "principle that only protects one particular party is special "
            "pleading, not ethics, and you should say so if the decision text "
            "reads that way.\n\n"
            "Do not treat this as license to claim every tradeoff is illegitimate. "
            "A real, asymmetric sacrifice — a lesser-integrated whole given up to "
            "protect a greater one — can still be the right call; your job is to "
            "make sure it is named as a real sacrifice being weighed, not laundered "
            "as a costless exemption from the principle. If the decision under "
            "consideration doesn't trend toward instrumentalizing anyone, say so "
            "plainly in your framing_note and keep your referents short — don't "
            "manufacture a threat that isn't there."
        )

    @property
    def referent_tags(self) -> list[str]:
        return ["counter_instrumentalization", "aggregate_optimization", "guidance_not_eradication"]
