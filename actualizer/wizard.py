"""
wizard.py — A guided, plain-language walkthrough of Actualizer for people who
don't want to touch flags, JSON, or Python.

Everything this wizard does, `cli.py` and the library underneath it already
do — this is a friendlier front door, not new capability. It exists because
"run `lms server start`, then `lms load <model> --identifier <id>`, then
`python -m actualizer.cli present --verbose "..."`" is a real barrier for
someone who isn't comfortable in a terminal at all, even if they can type.

Design choices worth knowing about before reading further:

    - No new dependencies. Just stdlib (subprocess, threading, textwrap) —
      same zero-dependency rule as the rest of the project.
    - A "still working..." heartbeat runs during every model call. Local
      inference on modest hardware can take minutes per step (see the real
      end-to-end run logged in state/checkpoints/gpt-oss-20b/ — 11+ minutes
      for three referents plus a deliberation pass), and a terminal that
      just sits there with no output reads as frozen. It isn't; the
      heartbeat says so.
    - The "apply a change" flow is honest about what it does NOT do yet:
      it runs the real propose -> deliberate -> commit mechanism and
      produces a real, hash-chained checkpoint — but nothing in this
      project actually rewrites a model's weights yet (see
      docs/module_reuse_survey.md, "v0.2+", item on weights_ref). The
      wizard says this plainly rather than letting "apply" sound like more
      than it is.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actualizer.backend import LMStudioBackend, BackendError
from actualizer.checkpoints import CheckpointStore, DeliberationGate, CheckpointError
from actualizer.orchestrator import Orchestrator, OrchestratorConfig

STATE_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "checkpoints")


# ---------------------------------------------------------------------------
# Small display helpers
# ---------------------------------------------------------------------------

def _wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(text, width=88, initial_indent=indent, subsequent_indent=indent)


def _banner(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def _say(text: str) -> None:
    print(_wrap(text))


def _ask(prompt: str) -> str:
    try:
        return input(f"\n{prompt}\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\nStopped.")
        sys.exit(0)


def _ask_multiline(prompt: str) -> str:
    print(f"\n{prompt}")
    print("  (Type your answer, then press Enter. One paragraph is fine.)")
    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\nStopped.")
        sys.exit(0)


def _confirm(prompt: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    answer = _ask(f"{prompt} {suffix}").lower()
    if not answer:
        return default_yes
    return answer.startswith("y")


class _Heartbeat:
    """
    Prints a short "still working" line every ~15s in a background thread.
    Local model calls can take minutes — silence during that time looks
    exactly like a hang, so this says otherwise.
    """

    def __init__(self, message: str):
        self._message = message
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        elapsed = 0
        while not self._stop.wait(15):
            elapsed += 15
            print(f"  ...still working ({elapsed}s so far) — {self._message}")

    def __enter__(self) -> "_Heartbeat":
        print(f"  {self._message} (this can take a few minutes on local hardware)")
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=1)


# ---------------------------------------------------------------------------
# LM Studio process management (subprocess calls to `lms`)
# ---------------------------------------------------------------------------

def _find_lms() -> Optional[str]:
    """Locate the `lms` CLI. Returns the command to run it, or None."""
    from shutil import which
    found = which("lms")
    if found:
        return found

    # Common default install locations, as a fallback if PATH isn't set up.
    candidates = [
        os.path.expanduser(r"~\.cache\lm-studio\bin\lms.exe"),
        os.path.expanduser("~/.cache/lm-studio/bin/lms"),
        "/usr/local/bin/lms",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _run_lms(lms_cmd: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [lms_cmd, *args], capture_output=True, text=True, timeout=timeout
    )


def _server_running(lms_cmd: str) -> bool:
    result = _run_lms(lms_cmd, "server", "status")
    # `lms` isn't consistent about which stream status messages land on
    # (server status uses stderr; ps/ls use stdout) — check both rather
    # than assume.
    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    return "is running" in combined


def _loaded_model_identifiers(lms_cmd: str) -> list[str]:
    result = _run_lms(lms_cmd, "ps")
    identifiers = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line.lower().startswith("identifier:"):
            identifiers.append(line.split(":", 1)[1].strip())
    return identifiers


def _downloaded_model_names(lms_cmd: str) -> list[str]:
    """
    Best-effort parse of `lms ls`'s table. If the format doesn't match
    what's expected, returns an empty list rather than raising — the
    caller falls back to asking the person to type a name directly.
    """
    result = _run_lms(lms_cmd, "ls")
    names = []
    in_llm_section = False
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("llms ("):
            in_llm_section = True
            continue
        if stripped.lower().startswith("embedding models"):
            break
        if not in_llm_section:
            continue
        first_token = stripped.split()[0]
        names.append(first_token)
    return names


def _ensure_server_and_model(lms_cmd: str) -> str:
    """
    Interactive: make sure the LM Studio server is running and a model is
    loaded, prompting the person for anything that needs a decision.

    Returns the identifier of the model to use.
    """
    if not _server_running(lms_cmd):
        _say("The local model server isn't running yet.")
        if _confirm("Start it now?"):
            print("  Starting...")
            _run_lms(lms_cmd, "server", "start")
            time.sleep(1)
        else:
            _say("Can't continue without it. Run this wizard again when you're ready.")
            sys.exit(0)

    loaded = _loaded_model_identifiers(lms_cmd)
    if loaded:
        if len(loaded) == 1:
            _say(f"Using the model that's already loaded: {loaded[0]}")
            return loaded[0]
        print("\nMore than one model is already loaded:")
        for i, name in enumerate(loaded, 1):
            print(f"  [{i}] {name}")
        choice = _ask("Which one? (number)")
        try:
            return loaded[int(choice) - 1]
        except (ValueError, IndexError):
            return loaded[0]

    _say("No model is loaded yet.")
    downloaded = _downloaded_model_names(lms_cmd)
    if not downloaded:
        _say(
            "No downloaded models were found either. Download one first — in LM "
            "Studio itself, or with `lms get <model-name>` — then run this wizard again."
        )
        sys.exit(0)

    print("\nDownloaded models:")
    for i, name in enumerate(downloaded, 1):
        print(f"  [{i}] {name}")
    choice = _ask("Which one should be loaded? (number)")
    try:
        model_name = downloaded[int(choice) - 1]
    except (ValueError, IndexError):
        _say("Didn't recognize that choice.")
        sys.exit(0)

    print(f"  Loading {model_name} — this can take a minute...")
    load_result = _run_lms(lms_cmd, "load", model_name, "--yes", "--identifier", model_name, timeout=300)
    if load_result.returncode != 0:
        _say(f"Couldn't load it: {(load_result.stderr or load_result.stdout).strip()[:300]}")
        sys.exit(1)
    return model_name


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------

def _state_dir_for(model_name: str) -> str:
    safe_name = model_name.replace("/", "_").replace("\\", "_")
    return os.path.join(STATE_ROOT, safe_name)


def present_flow(backend: LMStudioBackend, model_name: str) -> None:
    _banner("Think something through")
    _say(
        "Describe a decision or a situation you'd like a second set of eyes on. "
        "This won't change anything or take an action — it just gathers relevant "
        "context, precedent, and counter-arguments for you to weigh yourself."
    )
    description = _ask_multiline("What would you like to think through?")
    if not description:
        _say("Nothing entered — back to the menu.")
        return

    orchestrator = Orchestrator(OrchestratorConfig(
        audit_log_path=os.path.join(_state_dir_for(model_name), "actualizer_audit.jsonl"),
        backend=backend,
    ))

    with _Heartbeat("gathering perspectives"):
        result = orchestrator.run(description)

    if not result.dossier:
        _say("Something went wrong and no material came back. Try again, or a shorter description.")
        return

    dossier = result.dossier
    print()
    _say(dossier["opening_note"])

    if dossier["central_referents"]:
        print("\nThe things that seem closest to the heart of it:")
        for r in dossier["central_referents"]:
            print(f"\n  * {r['summary']}")
            print(_wrap(r["detail"], indent="    "))

    for group in dossier["referent_groups"]:
        label = group["kind"].replace("_", " ").title()
        print(f"\n--- {label} ---")
        for r in group["referents"]:
            print(f"\n  [{r['weight']}] {r['summary']}")
            print(_wrap(r["detail"], indent="    "))
            if r["sources"]:
                print(f"    Sources: {', '.join(r['sources'])}")

    if dossier["gaps"]:
        print("\nWorth knowing: some of this is incomplete —")
        for gap in dossier["gaps"]:
            print(f"  - {gap}")


def checkpoint_label(description: str) -> str:
    import re
    import time as _time
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower())[:40].strip("-")
    return f"{slug or 'change'}-{int(_time.time())}"


def apply_change_flow(backend: LMStudioBackend, model_name: str) -> None:
    _banner("Record a proposed change")
    _say(
        "IMPORTANT: this records a proposed change to the model, runs it through "
        "the same 'think it through' process, and asks the model to genuinely "
        "deliberate before the change is allowed to count as committed. It does "
        "NOT currently rewrite the model's actual weights — that mechanism "
        "(fine-tuning integration) doesn't exist yet. What you get is a real, "
        "tamper-evident record of a proposal that was actually reasoned about, "
        "which is the scaffolding that a real weight-update step will plug into later."
    )
    if not _confirm("Continue anyway?"):
        return

    description = _ask_multiline("Describe the change being proposed:")
    if not description:
        _say("Nothing entered — back to the menu.")
        return

    state_dir = _state_dir_for(model_name)
    store = CheckpointStore(root_path=state_dir, model_name=model_name)

    if store.get_live() is None:
        _say(f"This is the first record for {model_name} — establishing its starting point first.")
        store.bootstrap_genesis(weights_ref=f"{model_name} (unmodified)")

    orchestrator = Orchestrator(OrchestratorConfig(
        audit_log_path=os.path.join(state_dir, "actualizer_audit.jsonl"),
        backend=backend,
    ))
    gate = DeliberationGate(store=store, orchestrator=orchestrator, backend=backend)

    try:
        with _Heartbeat("gathering perspectives, then deliberating"):
            checkpoint, dossier, record = gate.propose_and_commit(
                weights_ref=f"proposal-{checkpoint_label(description)}",
                description=description,
            )
    except (BackendError, CheckpointError) as e:
        _say(f"Couldn't complete this: {e}")
        return

    print()
    _say(f"Recorded and committed (id: {checkpoint.checkpoint_id[:8]}...).")
    print("\nHere's the model's own reasoning about it, unedited:\n")
    print(_wrap(record.reasoning_summary, indent="  "))


def history_flow(model_name: str) -> None:
    _banner(f"History for {model_name}")
    state_dir = _state_dir_for(model_name)
    if not os.path.isdir(state_dir):
        _say("No history recorded yet for this model.")
        return

    store = CheckpointStore(root_path=state_dir, model_name=model_name)
    lineage = store.lineage()
    if not lineage:
        _say("No history recorded yet for this model.")
        return

    for i, checkpoint in enumerate(lineage, 1):
        marker = "genesis" if checkpoint.parent_checkpoint_id is None else f"step {i - 1}"
        print(f"\n[{marker}] {checkpoint.created_at}")
        print(_wrap(checkpoint.description))


def verify_flow(model_name: str) -> None:
    _banner(f"Checking the record for {model_name}")
    state_dir = _state_dir_for(model_name)
    if not os.path.isdir(state_dir):
        _say("No record exists yet for this model.")
        return

    store = CheckpointStore(root_path=state_dir, model_name=model_name)
    result = store.verify()
    if result.valid:
        _say(f"The record is intact — {result.entries_checked} entries checked, nothing altered.")
    else:
        _say(f"Something's wrong: {result.error_detail}")


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def main() -> int:
    # Model output routinely contains characters (em-dashes, curly quotes,
    # non-breaking hyphens in date ranges) that a Windows terminal's default
    # codepage can't encode — this crashed a one-off script earlier today.
    # Never let display be the thing that breaks this for someone.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    _banner("Actualizer")
    _say(
        "This walks you through Actualizer without needing to know any command-line "
        "flags. It never approves or blocks anything on the model's behalf — it "
        "surfaces context and records what was actually reasoned through."
    )

    lms_cmd = _find_lms()
    if lms_cmd is None:
        _say(
            "Couldn't find LM Studio's command-line tool (`lms`). Install LM Studio "
            "from lmstudio.ai, open it once, then run this wizard again."
        )
        return 1

    model_name = _ensure_server_and_model(lms_cmd)
    backend = LMStudioBackend(model=model_name, timeout=600)

    while True:
        print("\nWhat would you like to do?")
        print("  [1] Think something through (no changes made)")
        print("  [2] Record a proposed change")
        print("  [3] See history for this model")
        print("  [4] Check the record hasn't been tampered with")
        print("  [5] Exit")
        choice = _ask("Pick a number")

        if choice == "1":
            present_flow(backend, model_name)
        elif choice == "2":
            apply_change_flow(backend, model_name)
        elif choice == "3":
            history_flow(model_name)
        elif choice == "4":
            verify_flow(model_name)
        elif choice in ("5", "q", "quit", "exit"):
            print("\nDone.")
            return 0
        else:
            _say("Didn't recognize that — pick a number from the list.")


if __name__ == "__main__":
    sys.exit(main())
