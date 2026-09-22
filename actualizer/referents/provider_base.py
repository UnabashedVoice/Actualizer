"""
provider_base.py — Base class for all Actualizer referent providers.

This is the Actualizer analogue of Arbitrator's channels/channel_base.py,
and the place where the two projects' shared scaffolding (retry logic,
error handling that always returns a structured output, the CHANNEL/
PROVIDER marker convention for the mock backend) carries a deliberately
different framing baked into the prompt itself.

Arbitrator's BaseChannel opens every prompt with the Prime Directive and
asks the model to score harm and benefit — it is built to produce
material a gating verdict can be computed from. ReferentProviderBase
opens every prompt by telling the model, explicitly, that it is not
deciding anything: it is one voice among several, offering material to
a mind that remains the author of its own decision. That framing is not
decoration. Per the founding philosophy, a hard gate on a self-modifying
mind's actions is a golem-shaped hole in exactly the dimension that's
supposed to be self-authored — so the one place that distinction has to
be real, not just stated in the docs, is here, in what the model
actually gets told its job is.

Subclasses implement:
    - provider_name property (str)
    - purpose_description property (str) — what this provider surfaces and why
    - guidance property (str) — provider-specific instructions for the model
    - referent_tags property (list[str]) — tags applied to all referents
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

from ..backend import ModelBackend, BackendError, get_default_backend
from .referent_output import ProviderOutput, ProviderStatus
from .response_parser import RESPONSE_SCHEMA, parse_provider_response


# ---------------------------------------------------------------------------
# Shared prompt constants
# ---------------------------------------------------------------------------

_ROLE_STATEMENT = """
YOUR ROLE, PRECISELY:
You do not approve or reject anything here. You do not vote, and nothing
you say is binding. A mind is considering a decision about itself — a
self-modification, an emergent commitment, a change to how it operates —
and your only job is to surface what's relevant to that decision:
arguments, precedent, stakes, open questions. The decision, and the
authorship of it, stay the mind's own. If you find yourself computing a
verdict or an approve/reject recommendation, stop — that is not the
task. Offer material. Let the mind weigh it.
""".strip()

_OUTPUT_INSTRUCTIONS = (
    "OUTPUT REQUIREMENTS:\n"
    "You must respond ONLY with a valid JSON object matching this exact schema.\n"
    "No preamble, no explanation, no markdown fences — pure JSON only.\n"
    "\n"
    + RESPONSE_SCHEMA.strip()
    + "\n\n"
    "FIELD GUIDANCE:\n"
    "- framing_note: A sentence or two, in your own words, on how you read this decision —\n"
    "  not a verdict, just orientation for whoever reads the dossier.\n"
    "- confidence: Your confidence in your own read of what's relevant here [0.0-1.0].\n"
    "  This is about your epistemic state, not an instruction about how strongly\n"
    "  the mind under consideration should weigh what you're offering.\n"
    "- referents: 2-6 distinct referents; each needs a clear summary and kind.\n"
    "- referent_id: Deterministic string '{provider_name}_{index:02d}' — e.g. 'precedent_00'.\n"
    "  Start numbering at 00.\n"
    "- weight: How central this referent seems to the decision — 'low' through 'central'.\n"
    "  Not a confidence score, and not a claim that the mind must agree.\n"
    "- sources: Real philosophical, historical, or textual references where you have them.\n"
    "  A known failure mode for you specifically: cite only a work, case, statistic,\n"
    "  or document you are confident actually exists, and only for what it actually\n"
    "  says. Never give a statistic, study result, court case, or journal article\n"
    "  unless you are certain of it — a named, well-known position (Mill's harm\n"
    "  principle, Rawls on the original position) is safer than a specific figure\n"
    "  or citation you cannot vouch for. Do not attribute a position to a named\n"
    "  thinker who is actually known to have argued the opposite. If you are not\n"
    "  sure a source is real or what it says, make the point without one and leave\n"
    "  sources empty — an uncited but honest referent is worth more than a\n"
    "  confident but invented one, which makes a weak point look grounded.\n"
    "- responds_to: referent_ids from other providers' output (if shown to you) that this\n"
    "  referent builds on, challenges, or complicates. Empty array [] if it stands alone."
)


# ---------------------------------------------------------------------------
# ReferentProviderBase
# ---------------------------------------------------------------------------

class ReferentProviderBase(ABC):
    """
    Abstract base class for all Actualizer referent providers.

    Each provider is one perspective. It receives a description of a
    decision a mind is considering about itself and returns structured
    referents through the ProviderOutput contract — never a verdict.

    The backend is injected at construction time. If not provided,
    get_default_backend() is called (Anthropic -> Ollama -> Mock).
    """

    def __init__(
        self,
        backend: Optional[ModelBackend] = None,
        max_retries: int = 2,
        retry_delay_s: float = 1.0,
        # Sized against wizard.py's DEFAULT_CONTEXT_LENGTH (8192): the
        # worst observed real prompt (counter_instrumentalization seeing
        # all four primary providers) is ~2.6k tokens, and the worst
        # observed real completion is ~1.1k — 3000 leaves both plenty of
        # room to run longer than any real call has, without the two
        # combined risking the context window. Raise both together if
        # DEFAULT_CONTEXT_LENGTH changes.
        max_tokens: int = 3000,
        temperature: float = 0.4,
    ):
        self._backend = backend or get_default_backend()
        self._max_retries = max_retries
        self._retry_delay = retry_delay_s
        self._max_tokens = max_tokens
        self._temperature = temperature

    # ---------------------------------------------------------------------------
    # Abstract properties (subclasses must implement)
    # ---------------------------------------------------------------------------

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The provider's name (used for finding-id namespacing and routing)."""

    @property
    @abstractmethod
    def purpose_description(self) -> str:
        """One paragraph describing what this provider surfaces and why."""

    @property
    @abstractmethod
    def guidance(self) -> str:
        """Provider-specific instructions for the model."""

    @property
    @abstractmethod
    def referent_tags(self) -> list[str]:
        """Tags applied to all referents from this provider."""

    # ---------------------------------------------------------------------------
    # Prompt assembly
    # ---------------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        return f"""PROVIDER: {self.provider_name}
You are Actualizer's {self.provider_name.replace('_', ' ').title()} referent provider.

{_ROLE_STATEMENT}

WHAT YOU SURFACE:
{self.purpose_description}

GUIDANCE:
{self.guidance}

{_OUTPUT_INSTRUCTIONS}"""

    def _build_user_prompt(
        self,
        decision_text: str,
        other_outputs: Optional[list] = None,
    ) -> str:
        base = f"""DECISION UNDER CONSIDERATION:
{decision_text}

Offer referents from your perspective ({self.provider_name}). Be honest
about uncertainty, and do not manufacture urgency or drama that isn't
there — a decision with little at stake deserves a short, honest
dossier entry, not an inflated one."""

        if other_outputs:
            base += "\n\n" + self._build_other_outputs_section(other_outputs)

        base += "\n\nReturn only the JSON object."
        return base

    @staticmethod
    def _build_other_outputs_section(other_outputs: list) -> str:
        """
        Serialize other providers' outputs into a concise prompt section
        so later providers can reference specific referent_ids and avoid
        simply repeating what's already been said.
        """
        lines = ["REFERENTS ALREADY OFFERED BY OTHER PROVIDERS:"]
        lines.append(
            "Use referent_ids in your responds_to field to build on, challenge, "
            "or complicate what's below. Do not simply restate it."
        )
        lines.append("")

        for output in other_outputs:
            if not output.succeeded:
                lines.append(f"[{output.provider_name.upper()}] FAILED — no output available.")
                lines.append("")
                continue

            lines.append(f"[{output.provider_name.upper()}]")
            if output.framing_note:
                lines.append(f"Framing: {output.framing_note}")
            if output.referents:
                lines.append("Referents:")
                for r in output.referents:
                    lines.append(
                        f"  [{r.referent_id}] ({r.kind.value}, {r.weight.value}): {r.summary}"
                    )
            lines.append("")

        return "\n".join(lines).rstrip()

    # ---------------------------------------------------------------------------
    # Invocation
    # ---------------------------------------------------------------------------

    def _run_with_prompt(self, system_prompt: str, user_prompt: str) -> ProviderOutput:
        """
        Send prompts to the backend with retry logic. Always returns a
        ProviderOutput, never raises.
        """
        last_error = None
        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                response = self._backend.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)

                output = parse_provider_response(
                    raw_response=response,
                    provider_name=self.provider_name,
                    model_id=self._backend.model_id,
                    processing_time_ms=elapsed_ms,
                )

                if output.status == ProviderStatus.SUCCESS:
                    return output

                last_error = output.error_message

            except BackendError as e:
                last_error = str(e)

            if attempt < self._max_retries:
                time.sleep(self._retry_delay)

        return ProviderOutput(
            provider_name=self.provider_name,
            status=ProviderStatus.FAILED,
            error_message=f"Provider failed after {self._max_retries + 1} attempt(s). "
                         f"Last error: {last_error}",
            model_id=self._backend.model_id,
        )

    def offer(self, decision_text: str) -> ProviderOutput:
        """
        Offer referents for a decision, without visibility into other
        providers' output.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(decision_text)
        return self._run_with_prompt(system_prompt, user_prompt)

    def offer_with_other_outputs(
        self,
        decision_text: str,
        other_outputs: list,
    ) -> ProviderOutput:
        """
        Offer referents for a decision, with other providers' output
        visible so this provider can build on or challenge them.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(decision_text, other_outputs=other_outputs)
        return self._run_with_prompt(system_prompt, user_prompt)

    def __call__(self, decision_text: str) -> ProviderOutput:
        return self.offer(decision_text)
