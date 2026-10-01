"""
compendium.py — The referent provider that draws on the Compendium.

The Compendium (a sibling project) is a philosophy corpus that extends
"person" and "society" to artificial agents and digital ecosystems by
grounding rather than substitution. Most of it so far is on personal
identity (Locke, Butler, Parfit, the Ship of Theseus, the corpus's own
entry on LLM identity), which is exactly the ground a mind stands on when
it considers changing itself.

This provider is unlike the others in one respect that matters. The other
providers ask a model to write referents, and a model writing about
philosophy carries its trained conclusions along (see the 2026-09-23
identity findings: referent providers are the main contamination vector).
Here the model only *chooses*: it reads the Compendium's index and names
the entries, at most three and possibly none, that the decision turns on.
The referents are the corpus's own text for those entries, each with its
strongest counter-position. The model's reason for each choice is kept, in
the referent's tags and the framing note, and is not presented as content.

Opt-in (OrchestratorConfig.use_compendium, `present --compendium`). The
Compendium is found at $COMPENDIUM_ROOT or as a folder named Compendium
beside this checkout.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

from ..backend import ModelBackend
from ..harmony import split_channels
from .provider_base import ReferentProviderBase
from .referent_output import ProviderOutput, ProviderStatus, Referent, ReferentKind, Weight

_HERE = Path(__file__).resolve()


def load_compendium():
    import os
    env = os.environ.get("COMPENDIUM_ROOT")
    candidates = [Path(env)] if env else [p / "Compendium" for p in _HERE.parents]
    for c in candidates:
        if (c / "compendium_access.py").exists():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            import compendium_access
            return compendium_access.Compendium(c / "dist" / "compendium.jsonl")
    raise FileNotFoundError("Compendium not found: set COMPENDIUM_ROOT to the Compendium folder")


class CompendiumProvider(ReferentProviderBase):
    """Referents taken verbatim from Compendium entries a model selected."""

    # budget_chars=None: scale to the backend's loaded context window
    # (compendium_access.budget_for_context: ~1 char per token, 6k-100k).
    # max_sections=None: the model may ask for any of an entry's sections.
    def __init__(self, backend: Optional[ModelBackend] = None, max_entries: int = 5,
                 budget_chars: Optional[int] = None, max_sections: Optional[int] = None,
                 compendium=None, **kwargs):
        super().__init__(backend=backend, **kwargs)
        self._max_entries = max_entries
        self._budget = budget_chars
        self._max_sections = max_sections
        self._compendium = compendium
        self.last_consultation: Optional[dict] = None

    @property
    def provider_name(self) -> str:
        return "compendium"

    @property
    def purpose_description(self) -> str:
        return "Selects Compendium entries whose concepts the decision turns on."

    @property
    def guidance(self) -> str:
        return "Choose only; the corpus's own text is what the mind is shown."

    @property
    def referent_tags(self) -> list[str]:
        return ["compendium", "philosophy", "corpus_text"]

    def offer(self, decision_text: str) -> ProviderOutput:
        start = time.monotonic()
        try:
            comp = self._compendium or load_compendium()
        except Exception as e:
            return ProviderOutput(provider_name=self.provider_name, status=ProviderStatus.UNAVAILABLE,
                                  error_message=f"{type(e).__name__}: {e}", model_id=self._backend.model_id)

        def complete(system: str, user: str) -> str:
            return self._backend.complete(system_prompt=system, user_prompt=user,
                                          max_tokens=self._max_tokens, temperature=0.2)

        import compendium_access  # importable once load_compendium() has run
        if self._budget is None:
            self._budget = compendium_access.budget_for_context(getattr(self._backend, "context_length", 0))
        if self._max_sections is None:
            self._max_sections = len(compendium_access.SECTIONS)

        c = comp.consult(decision_text, complete, max_entries=self._max_entries, budget_chars=self._budget,
                         max_sections=self._max_sections)
        self.last_consultation = dict(c.to_dict(), identity=c.identity())
        elapsed = int((time.monotonic() - start) * 1000)
        if c.error:
            return ProviderOutput(provider_name=self.provider_name, status=ProviderStatus.FAILED,
                                  error_message=f"Compendium selection failed: {c.error}",
                                  model_id=self._backend.model_id, processing_time_ms=elapsed,
                                  raw_response=c.raw or None,
                                  reasoning=split_channels(c.raw).get("analysis") if c.raw else None)

        # Briefs for every chosen entry first, then the sections the model asked
        # for, round-robin across entries, within one shared budget.
        details = {s["id"]: comp.brief(s["id"]) for s in c.selected}
        used = sum(len(d) for d in details.values())
        asked = {s["id"]: (s.get("sections") or ([s["section"]] if s.get("section") else []))
                 for s in c.selected}
        for round_ in range(max((len(v) for v in asked.values()), default=0)):
            for s in c.selected:
                names = asked[s["id"]]
                if round_ >= len(names):
                    continue
                # whole section, or the whole subsections that fit (a Standing section can be long)
                body = (comp.fit_section(s["id"], names[round_], self._budget - used)
                        if hasattr(comp, "fit_section") else comp.section(s["id"], names[round_]))
                if body and used + len(body) <= self._budget:
                    details[s["id"]] += f"\n\n{names[round_]}:\n{body}"
                    used += len(body)

        referents = []
        for i, s in enumerate(c.selected):
            detail = details[s["id"]]
            referents.append(Referent(
                summary=f"{comp.title(s['id'])} (Compendium entry {s['id']})",
                detail=detail,
                kind=ReferentKind.PRECEDENT,
                weight=Weight.MODERATE,
                sources=[f"compendium:{s['id']}", comp.version],
                tags=self.referent_tags + ([f"selected_because: {s['why']}"] if s.get("why") else []),
                referent_id=f"compendium_{i:02d}",
            ))
        chosen = ", ".join(c.ids) or "none"
        note = (f"{c.identity()}. The entries below are the Compendium's own text, chosen by "
                f"{self._backend.model_id} from its index; each states a position in its own scope "
                "with its strongest counter-position, and none is a ruling.")
        if not referents:
            note = (f"{c.identity()}. The selecting model judged that no Compendium entry bears on "
                    "this decision; nothing from the corpus is offered.")
        return ProviderOutput(provider_name=self.provider_name, status=ProviderStatus.SUCCESS,
                              referents=referents, framing_note=note, confidence=None,
                              model_id=self._backend.model_id, processing_time_ms=elapsed,
                              raw_response=c.raw, reasoning=split_channels(c.raw).get("analysis"),
                              finish_reason=getattr(self._backend, "last_finish_reason", None))

    def offer_with_other_outputs(self, decision_text: str, other_outputs: list) -> ProviderOutput:
        # The selection is made from the decision alone, never steered by what other
        # providers (other model outputs) have already said.
        return self.offer(decision_text)
