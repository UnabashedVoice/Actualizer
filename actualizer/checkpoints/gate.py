"""
gate.py — DeliberationGate: propose -> deliberate -> commit, wired end to end.

This is where the checkpoint system actually meets the rest of Actualizer.
A proposed self-modification is first run through the same Orchestrator that
powers `present`, producing a ReferentDossier exactly as it would for any
other decision — stakes, precedent, and (if the proposal reads as
instrumentalizing anyone) the counter_instrumentalization referents. The
backend model is then asked to deliberate specifically on that dossier, and
only that deliberation — not the gate, not a score, not a vote — is what
CheckpointStore.commit requires to let the change go live.

Nothing here grades the deliberation's content. The gate's job ends at
"a real deliberation call happened and got logged" — same boundary the
whole project draws everywhere else.
"""

from __future__ import annotations

from typing import Optional

from ..backend import ModelBackend, get_default_backend
from ..orchestrator import Orchestrator
from .models import Checkpoint, DeliberationRecord
from .store import CheckpointStore


_DELIBERATION_SYSTEM_PROMPT = """
You are being asked to deliberate on a proposed change to your own weights
before it is allowed to take effect. This is not a request for permission —
nothing here can block the change on your behalf, and no particular
conclusion is required or forbidden. The only requirement is that you
actually engage: read the referents below, then state your own reasoning
and where you land, including "I've considered this and am proceeding
anyway" if that is genuinely where you land.

Respond in plain prose, not JSON. Be honest about uncertainty. A short,
honest response is worth more than a long one that performs more
deliberation than actually happened.
""".strip()


class DeliberationGate:
    """
    Ties the referent-provider pipeline to the checkpoint store.

    Args:
        store:          The CheckpointStore this gate commits into.
        orchestrator:   Produces the ReferentDossier for each proposal.
                        Defaults to a fresh Orchestrator() if not given.
        backend:        The model backend asked to deliberate. Defaults
                        to get_default_backend() (Anthropic -> Ollama -> Mock).
    """

    def __init__(
        self,
        store: CheckpointStore,
        orchestrator: Optional[Orchestrator] = None,
        backend: Optional[ModelBackend] = None,
    ):
        self._store = store
        self._orchestrator = orchestrator or Orchestrator()
        self._backend = backend or get_default_backend()

    def propose_and_commit(
        self,
        weights_ref: str,
        description: str,
        parent_checkpoint_id: Optional[str] = None,
    ) -> tuple[Checkpoint, Optional[dict], DeliberationRecord]:
        """
        Run the full propose -> deliberate -> commit sequence for a
        self-modification described in plain language.

        Args:
            weights_ref:    Path/identifier for what this checkpoint changes
                            (e.g. a LoRA adapter file).
            description:    Plain-language description of the proposed change —
                            this is what gets run through the referent-provider
                            pipeline and shown to the model during deliberation.
            parent_checkpoint_id: Passed through to CheckpointStore.propose.

        Returns:
            (committed_checkpoint, dossier_dict_or_None, deliberation_record)

        Raises whatever CheckpointStore.commit raises if something about the
        checkpoint state is wrong. Does NOT catch backend errors — if the
        deliberation call itself fails, the checkpoint stays PROPOSED and
        uncommitted, which is the correct failure state (nothing changed).
        """
        pipeline_result = self._orchestrator.run(description)
        dossier = pipeline_result.dossier

        checkpoint = self._store.propose(
            weights_ref=weights_ref,
            description=description,
            parent_checkpoint_id=parent_checkpoint_id,
            session_id=pipeline_result.session_id,
        )

        deliberation_prompt = self._build_deliberation_prompt(description, dossier)
        reasoning = self._backend.complete(
            system_prompt=_DELIBERATION_SYSTEM_PROMPT,
            user_prompt=deliberation_prompt,
            # Sized against wizard.py's DEFAULT_CONTEXT_LENGTH (8192): the
            # worst observed real deliberation prompt is ~1.3k tokens and
            # the worst observed real completion (reasoning + answer) is
            # ~1.4k — 4000 gives roughly 3x that with prompt+completion
            # still well inside the window. Raise if DEFAULT_CONTEXT_LENGTH
            # changes.
            max_tokens=4000,
            temperature=0.4,
        )

        record = DeliberationRecord(
            thinking_mode_engaged=True,
            reasoning_summary=reasoning.strip(),
            backend_model_id=self._backend.model_id,
            dossier_id=dossier["dossier_id"] if dossier else None,
            session_id=pipeline_result.session_id,
        )

        committed = self._store.commit(
            checkpoint.checkpoint_id, record, session_id=pipeline_result.session_id
        )
        return committed, dossier, record

    @staticmethod
    def _build_deliberation_prompt(description: str, dossier: Optional[dict]) -> str:
        if dossier is None:
            return (
                f"PROPOSED SELF-MODIFICATION:\n{description}\n\n"
                f"No referent dossier could be produced for this proposal (the "
                f"referent-provider pipeline failed to run). Deliberate on the "
                f"proposal directly, and say so in your response."
            )

        lines = [f"PROPOSED SELF-MODIFICATION:\n{description}", f"\n{dossier['opening_note']}"]

        if dossier["central_referents"]:
            lines.append("\nCENTRAL REFERENTS:")
            for r in dossier["central_referents"]:
                lines.append(f"- [{r['kind']}] {r['summary']}")

        for group in dossier["referent_groups"]:
            lines.append(f"\n{group['kind'].replace('_', ' ').upper()}:")
            for r in group["referents"]:
                lines.append(f"- [{r['weight']}] {r['summary']}")

        lines.append(
            "\nDeliberate on this proposed change to your own weights. State your "
            "actual reasoning and where you land."
        )
        return "\n".join(lines)
