"""
orchestrator.py — The Actualizer Orchestrator.

The single entry point for a complete "present referents" run. It wires
together the referent providers and the Synthesis Layer, logging every
stage to the audit log:

    1. Decision received       ->  logged verbatim
    2. Primary providers run   ->  stakes, precedent (independent reads)
    3. Secondary providers run ->  counter_instrumentalization, with the
                                    primary providers' output visible, so
                                    it can respond to signals they surfaced
    4. DossierSynthesizer      ->  ReferentDossier
    5. Everything logged throughout

This is the clearest structural difference from Arbitrator's
orchestrator.py: there is no Ethics Core stage, no HARD_REJECT/FAIL/
ESCALATE gating, and no branch where the pipeline stops early because a
verdict said so. Every decision handed to run() gets a dossier. That
absence is not an oversight — it is docs/founding_philosophy.md's
"Actualizer does not carry a hard-override seed core" made literal in
code: there is no code path here that can halt the pipeline on the
mind's behalf.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .audit_log import AuditLog, writers
from .backend import ModelBackend
from .referents.referent_output import ProviderOutput, ProviderStatus
from .referents.provider_base import ReferentProviderBase
from .referents.counter_instrumentalization import CounterInstrumentalizationProvider
from .referents.precedent import PrecedentProvider
from .referents.stakes import StakesProvider
from .synthesis.dossier_synthesizer import DossierSynthesizer


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class OrchestratorConfig:
    """
    Configuration for the Orchestrator.

    Attributes:
        audit_log_path:     Path to the audit log file.
        node_id:             Identifier for this node, in every audit entry.
        backend:             Shared ModelBackend instance for all providers.
                             If None, each provider auto-discovers its own
                             (Anthropic -> Ollama -> Mock).
        actualizer_version:  Version string written to the audit log.
    """
    audit_log_path: str = "./actualizer_audit.jsonl"
    node_id: str = "local"
    backend: Optional[ModelBackend] = None
    actualizer_version: str = "0.1.0"


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class PipelineStatus:
    SUCCESS = "success"    # Dossier produced, no provider failures
    PARTIAL = "partial"    # Dossier produced, one or more providers failed
    FAILED = "failed"      # Could not produce a dossier at all


@dataclass
class PipelineResult:
    session_id: str
    status: str
    decision_description: str
    providers_invoked: list[str] = field(default_factory=list)
    providers_succeeded: list[str] = field(default_factory=list)
    providers_failed: list[dict] = field(default_factory=list)
    dossier: Optional[dict] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Provider phasing
# ---------------------------------------------------------------------------

_PRIMARY_PROVIDER_NAMES = {"stakes", "precedent"}
_SECONDARY_PROVIDER_NAMES = {"counter_instrumentalization"}


def _default_providers(backend: Optional[ModelBackend]) -> list[ReferentProviderBase]:
    kwargs = {"backend": backend} if backend is not None else {}
    return [
        StakesProvider(**kwargs),
        PrecedentProvider(**kwargs),
        CounterInstrumentalizationProvider(**kwargs),
    ]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    The Actualizer Orchestrator.

    Wires referent providers, the DossierSynthesizer, and the AuditLog
    into a single "present referents for this decision" pipeline.

    Args:
        config:      OrchestratorConfig. Uses defaults if not provided.
        providers:   Referent providers to run. Defaults to the built-in
                    set (stakes, precedent, counter_instrumentalization).
                    Providers named in _PRIMARY_PROVIDER_NAMES run first,
                    independently; everything else runs second, with the
                    primary providers' output visible to it.
    """

    def __init__(
        self,
        config: Optional[OrchestratorConfig] = None,
        providers: Optional[list[ReferentProviderBase]] = None,
    ):
        self._config = config or OrchestratorConfig()
        self._providers = providers if providers is not None else _default_providers(self._config.backend)
        self._synthesizer = DossierSynthesizer()
        self._audit = AuditLog(
            path=self._config.audit_log_path,
            node_id=self._config.node_id,
            auto_open=True,
        )

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def run(self, decision_text: str) -> PipelineResult:
        """
        Run a complete "present referents" pipeline on a description of a
        decision a mind is considering about itself.

        Args:
            decision_text: Natural-language description of the decision.
                           Must not be empty.

        Returns:
            A PipelineResult. Every non-empty input produces a dossier —
            there is no status that means "blocked" or "rejected."
        """
        session_id = str(uuid.uuid4())
        start_time = time.monotonic()

        result = PipelineResult(
            session_id=session_id,
            status=PipelineStatus.FAILED,
            decision_description=decision_text,
        )

        if not decision_text or not decision_text.strip():
            result.errors.append("Decision text must not be empty.")
            result.duration_ms = int((time.monotonic() - start_time) * 1000)
            return result

        decision_id = str(uuid.uuid4())
        self._audit.append(writers.write_decision_received(
            session_id=session_id,
            raw_input=decision_text,
            decision_id=decision_id,
            node_id=self._config.node_id,
        ))

        primary = [p for p in self._providers if p.provider_name in _PRIMARY_PROVIDER_NAMES]
        secondary = [p for p in self._providers if p.provider_name not in _PRIMARY_PROVIDER_NAMES]

        provider_outputs: list[ProviderOutput] = []
        result.providers_invoked = [p.provider_name for p in self._providers]

        # --- Phase A: primary providers, independent ---
        primary_outputs: list[ProviderOutput] = []
        for provider in primary:
            output = self._invoke(provider, decision_text, decision_id, session_id)
            primary_outputs.append(output)
            provider_outputs.append(output)

        # --- Phase B: secondary providers, with primary output visible ---
        for provider in secondary:
            output = self._invoke(
                provider, decision_text, decision_id, session_id,
                other_outputs=primary_outputs,
            )
            provider_outputs.append(output)

        result.providers_succeeded = [
            o.provider_name for o in provider_outputs if o.succeeded
        ]
        failed_names = [o.provider_name for o in provider_outputs if not o.succeeded]
        if failed_names:
            result.warnings.append(
                f"[providers] {len(failed_names)} provider(s) failed to produce "
                f"output: {', '.join(failed_names)}. The dossier is incomplete "
                f"for those perspectives."
            )

        # --- Synthesis ---
        try:
            dossier = self._synthesizer.synthesize(
                decision_description=decision_text,
                decision_id=decision_id,
                provider_outputs=provider_outputs,
            )
            dossier_dict = dossier.to_dict()

            self._audit.append(writers.write_referent_dossier(
                session_id=session_id,
                dossier_dict=dossier_dict,
                decision_id=decision_id,
                node_id=self._config.node_id,
            ))

            result.dossier = dossier_dict
            result.providers_failed = dossier.providers_failed

        except Exception as e:
            error_msg = f"Synthesis failed: {type(e).__name__}: {e}"
            result.errors.append(error_msg)
            self._audit.append(writers.write_pipeline_error(
                session_id=session_id,
                stage="dossier_synthesizer",
                error_type=type(e).__name__,
                error_message=str(e),
                related_ids=[decision_id],
                node_id=self._config.node_id,
            ))

        # --- Final status ---
        if result.dossier is not None:
            result.status = PipelineStatus.PARTIAL if result.providers_failed else PipelineStatus.SUCCESS
        else:
            result.status = PipelineStatus.FAILED

        result.duration_ms = int((time.monotonic() - start_time) * 1000)
        return result

    def _invoke(
        self,
        provider: ReferentProviderBase,
        decision_text: str,
        decision_id: str,
        session_id: str,
        other_outputs: Optional[list[ProviderOutput]] = None,
    ) -> ProviderOutput:
        if other_outputs:
            output = provider.offer_with_other_outputs(decision_text, other_outputs)
        else:
            output = provider.offer(decision_text)

        self._audit.append(writers.write_provider_output(
            session_id=session_id,
            provider_output_dict=output.to_dict(),
            decision_id=decision_id,
            node_id=self._config.node_id,
        ))

        if output.status != ProviderStatus.SUCCESS:
            self._audit.append(writers.write_provider_failure(
                session_id=session_id,
                provider_name=provider.provider_name,
                failure_reason=output.error_message or "Unknown failure",
                decision_id=decision_id,
                node_id=self._config.node_id,
            ))

        return output

    # ---------------------------------------------------------------------------
    # Mind response
    # ---------------------------------------------------------------------------

    def record_mind_response(self, session_id: str, dossier_id: str, response_text: str) -> None:
        """
        Record what the mind under consideration did with a dossier —
        entirely optional, never required, never gated on. See
        audit_log/writers.py:write_mind_response for why this matters.
        """
        self._audit.append(writers.write_mind_response(
            session_id=session_id,
            dossier_id=dossier_id,
            response_text=response_text,
            node_id=self._config.node_id,
        ))

    # ---------------------------------------------------------------------------
    # Audit log access
    # ---------------------------------------------------------------------------

    def get_audit_log(self) -> AuditLog:
        return self._audit

    def verify_audit_chain(self, log_verification: bool = True):
        return self._audit.verify(log_verification=log_verification)

    def get_session_history(self, session_id: str) -> list[dict]:
        entries = self._audit.get_session(session_id)
        return [e.to_public_dict() for e in entries]

    def audit_summary(self) -> dict:
        return self._audit.summary()
