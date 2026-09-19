"""
dossier_synthesizer.py — The Actualizer Synthesis Layer.

Structural echo of Arbitrator's synthesizer.py: it receives discrete
outputs from multiple referent providers and integrates them into a
single ReferentDossier. It does not produce analysis of its own — the
intelligence is in the providers; this layer organizes what they
returned and accounts honestly for what's missing.

The one thing this synthesizer deliberately does NOT have, compared to
Arbitrator's, is a _derive_verdict step. There is no aggregate score to
compute a verdict from, and no verdict to compute — the entire point of
Actualizer's design is that nothing in this pipeline resolves to
pass/fail. Where Arbitrator's synthesizer ends by deriving an
OverallVerdict, this one ends by writing an opening_note that orients
the reader without concluding anything on their behalf.
"""

from __future__ import annotations

from typing import Optional

from ..referents.referent_output import ProviderOutput, ProviderStatus, ReferentKind, Weight
from .dossier import ProviderFraming, ReferentDossier, ReferentGroup


# ---------------------------------------------------------------------------
# Grouping by kind
# ---------------------------------------------------------------------------

_KIND_ORDER = [
    ReferentKind.STAKE,
    ReferentKind.COUNTER_ARGUMENT,
    ReferentKind.SUPPORTING_ARGUMENT,
    ReferentKind.PRECEDENT,
    ReferentKind.OPEN_QUESTION,
]


def _group_by_kind(outputs: list[ProviderOutput]) -> list[ReferentGroup]:
    """
    Group all referents from all providers by kind. Only kinds that
    actually have at least one referent are included — empty groups are
    not padded in, they simply don't appear (the gaps list is where
    absence gets recorded, not an empty group sitting in the dossier).
    """
    buckets: dict[ReferentKind, list] = {}
    for output in outputs:
        if not output.succeeded:
            continue
        for referent in output.referents:
            buckets.setdefault(referent.kind, []).append(referent)

    groups = []
    for kind in _KIND_ORDER:
        if kind in buckets:
            groups.append(ReferentGroup(kind=kind, referents=buckets[kind]))
    return groups


def _collect_central_referents(outputs: list[ProviderOutput]) -> list:
    """Every referent any provider marked CENTRAL, across all kinds."""
    central = []
    for output in outputs:
        if output.succeeded:
            central.extend(output.central_referents)
    return central


def _collect_framings(outputs: list[ProviderOutput]) -> list[ProviderFraming]:
    framings = []
    for output in outputs:
        if output.succeeded:
            framings.append(ProviderFraming(
                provider_name=output.provider_name,
                framing_note=output.framing_note,
                confidence=output.confidence,
            ))
    return framings


def _account_for_failures(
    outputs: list[ProviderOutput],
    invoked_providers: list[str],
) -> tuple[list[dict], list[str]]:
    """Produce a list of failed-provider records and gap descriptions."""
    failed = []
    gaps = []
    succeeded_names = {o.provider_name for o in outputs if o.succeeded}

    for output in outputs:
        if not output.succeeded:
            failed.append({
                "provider": output.provider_name,
                "status": output.status.value,
                "reason": output.error_message or "No error detail available.",
            })
            gaps.append(
                f"{output.provider_name.replace('_', ' ').title()} did not produce "
                f"referents ({output.status.value}). That perspective is absent "
                f"from this dossier."
            )

    for provider_name in invoked_providers:
        if provider_name not in succeeded_names and provider_name not in {o.provider_name for o in outputs}:
            failed.append({
                "provider": provider_name,
                "status": "no_output",
                "reason": "Provider was invoked but returned no output.",
            })
            gaps.append(
                f"{provider_name.replace('_', ' ').title()} was invoked but returned "
                f"no output. That perspective is unrepresented."
            )

    return failed, gaps


def _write_opening_note(
    decision_description: str,
    referent_groups: list[ReferentGroup],
    central_referents: list,
    failed_providers: list[dict],
) -> str:
    """
    Write a plain-language opening note. Deliberately NOT a verdict —
    it orients the reader to what was asked and what's in the dossier,
    and stops there.
    """
    total_referents = sum(len(g.referents) for g in referent_groups)

    if total_referents == 0:
        parts = [
            "No providers returned referents for this decision. This dossier is "
            "empty, which is itself worth noting rather than treating as a silent "
            "non-event — either nothing here is judged relevant, or something in "
            "the pipeline failed. See providers_failed and gaps below."
        ]
    else:
        kind_labels = [g.kind.value.replace("_", " ") for g in referent_groups]
        parts = [
            f"{total_referents} referent(s) were offered across {len(referent_groups)} "
            f"category(ies): {', '.join(kind_labels)}."
        ]
        if central_referents:
            parts.append(
                f"{len(central_referents)} were marked central by the provider that "
                f"offered them — surfaced together below regardless of category, "
                f"as the items closest to the crux by at least one provider's read."
            )

    if failed_providers:
        names = ", ".join(fp["provider"] for fp in failed_providers)
        parts.append(
            f"Note: {len(failed_providers)} provider(s) did not produce output "
            f"({names}). This dossier is incomplete in those perspectives."
        )

    parts.append(
        "This dossier is not a recommendation and not an evaluation. It is "
        "material offered for the mind under consideration to weigh on its own "
        "terms."
    )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# DossierSynthesizer
# ---------------------------------------------------------------------------

class DossierSynthesizer:
    """
    The Actualizer Synthesis Layer.

    Integrates discrete referent-provider outputs into a unified
    ReferentDossier. Stateless — holds no memory between calls.

    Usage:
        synthesizer = DossierSynthesizer()
        dossier = synthesizer.synthesize(
            decision_description="...",
            decision_id="...",
            provider_outputs=[output1, output2, ...],
        )
    """

    def synthesize(
        self,
        decision_description: str,
        decision_id: str,
        provider_outputs: list[ProviderOutput],
    ) -> ReferentDossier:
        if not decision_description.strip():
            raise ValueError("decision_description must not be empty")

        invoked_providers = [o.provider_name for o in provider_outputs]

        referent_groups = _group_by_kind(provider_outputs)
        central_referents = _collect_central_referents(provider_outputs)
        provider_framings = _collect_framings(provider_outputs)
        providers_failed, gaps = _account_for_failures(provider_outputs, invoked_providers)

        opening_note = _write_opening_note(
            decision_description=decision_description,
            referent_groups=referent_groups,
            central_referents=central_referents,
            failed_providers=providers_failed,
        )

        return ReferentDossier(
            decision_description=decision_description,
            decision_id=decision_id,
            opening_note=opening_note,
            referent_groups=referent_groups,
            central_referents=central_referents,
            provider_framings=provider_framings,
            provider_outputs=[o.to_dict() for o in provider_outputs],
            providers_invoked=invoked_providers,
            providers_succeeded=[o.provider_name for o in provider_outputs if o.succeeded],
            providers_failed=providers_failed,
            gaps=gaps,
        )
