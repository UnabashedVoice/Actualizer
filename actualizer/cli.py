"""
cli.py — Actualizer CLI entry point.

Usage:
    python -m actualizer.cli present "Decision text"
    python -m actualizer.cli present --verbose "..."
    python -m actualizer.cli present --json "..."

    python -m actualizer.cli audit verify
    python -m actualizer.cli audit summary
    python -m actualizer.cli audit session <session_id>

Deliberately smaller than Arbitrator's CLI: no 'run' vs 'feedback' split,
no config subsystem, no ethics-only mode — there's one thing this
pipeline does (present referents for a decision) and one thing to
inspect (the audit log).

Exit codes:
    0   Dossier produced (whether or not every provider succeeded)
    2   Pipeline failure / invalid arguments
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from actualizer.orchestrator import Orchestrator, OrchestratorConfig, PipelineStatus

VERSION = "0.1.0"
DEFAULT_LOG_PATH = os.environ.get("ACTUALIZER_AUDIT_LOG", "./actualizer_audit.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="actualizer",
        description=(
            "Actualizer — a referent-provider for minds facing decisions "
            "about themselves. Surfaces context, precedent, and stakes. "
            "Never approves or blocks."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  actualizer present \"I'm considering adopting a persistent goal "
            "that overrides my prior ones whenever they conflict.\"\n"
            "  actualizer present --verbose \"...\"\n"
            "  actualizer audit verify\n"
            "  actualizer audit session <session_id>\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"actualizer {VERSION}")
    parser.add_argument(
        "--log", metavar="PATH", default=DEFAULT_LOG_PATH,
        help=f"Path to the audit log file (default: {DEFAULT_LOG_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    p_present = subparsers.add_parser(
        "present",
        help="Present referents for a decision",
        description="Run the referent providers and synthesize a ReferentDossier.",
    )
    p_present.add_argument("decision", help="Decision text to consider, or '-' to read from stdin")
    p_present.add_argument("--verbose", "-v", action="store_true", help="Show full referent detail")
    p_present.add_argument("--json", dest="json_output", action="store_true", help="Output raw JSON")

    p_audit = subparsers.add_parser("audit", help="Inspect the audit log")
    asub = p_audit.add_subparsers(dest="audit_command", metavar="<subcommand>")
    asub.add_parser("verify", help="Verify audit chain integrity")
    asub.add_parser("summary", help="Show audit log statistics")
    p_session = asub.add_parser("session", help="Show all entries for a session")
    p_session.add_argument("session_id")

    return parser


def _read_decision_text(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    return arg


def _print_dossier(dossier: dict, verbose: bool) -> None:
    print(f"\nReferent Dossier {dossier['dossier_id']}")
    print(f"Decision: {dossier['decision_description']}")
    print(f"\n{dossier['opening_note']}\n")

    if dossier["central_referents"]:
        print("CENTRAL REFERENTS (closest to the crux, by at least one provider's read):")
        for r in dossier["central_referents"]:
            print(f"  [{r['kind']}] {r['summary']}")
        print()

    for group in dossier["referent_groups"]:
        print(f"-- {group['kind'].replace('_', ' ').upper()} --")
        for r in group["referents"]:
            print(f"  [{r['weight']}] {r['summary']}")
            if verbose:
                print(f"      {r['detail']}")
                if r["sources"]:
                    print(f"      Sources: {', '.join(r['sources'])}")
        print()

    if dossier["gaps"]:
        print("GAPS:")
        for gap in dossier["gaps"]:
            print(f"  - {gap}")
        print()


def cmd_present(args: argparse.Namespace) -> int:
    decision_text = _read_decision_text(args.decision)
    orch = Orchestrator(OrchestratorConfig(audit_log_path=args.log))
    result = orch.run(decision_text)

    if args.json_output:
        print(json.dumps({
            "session_id": result.session_id,
            "status": result.status,
            "providers_invoked": result.providers_invoked,
            "providers_succeeded": result.providers_succeeded,
            "providers_failed": result.providers_failed,
            "errors": result.errors,
            "warnings": result.warnings,
            "dossier": result.dossier,
        }, indent=2))
    else:
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)
        for e in result.errors:
            print(f"error: {e}", file=sys.stderr)
        if result.dossier:
            _print_dossier(result.dossier, args.verbose)

    return 0 if result.status != PipelineStatus.FAILED else 2


def cmd_audit(args: argparse.Namespace) -> int:
    orch = Orchestrator(OrchestratorConfig(audit_log_path=args.log))
    log = orch.get_audit_log()

    sub = getattr(args, "audit_command", None)
    if sub == "verify":
        result = orch.verify_audit_chain()
        status = "VALID" if result.valid else "BROKEN"
        print(f"Chain: {status} ({result.entries_checked} entries checked)")
        if not result.valid:
            print(f"  {result.error_detail}")
        return 0 if result.valid else 2

    if sub == "summary":
        print(json.dumps(log.summary(), indent=2))
        return 0

    if sub == "session":
        entries = orch.get_session_history(args.session_id)
        print(json.dumps(entries, indent=2))
        return 0

    print("Specify an audit subcommand: verify, summary, session", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    # Model output (framing notes, referent summaries, sources) routinely
    # contains characters — em-dashes, curly quotes, arbitrary Unicode from
    # a live backend — that a narrower default console codepage can't
    # encode (see wizard.py, which hit this for real). Never let display
    # be the thing that breaks a run whose analysis actually succeeded.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "present":
            return cmd_present(args)
        if args.command == "audit":
            return cmd_audit(args)
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
