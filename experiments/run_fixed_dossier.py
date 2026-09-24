"""
run_fixed_dossier.py — sample deliberations with the referent dossier held
fixed, so the only thing varying is what you choose to vary: the deliberating
model, or (for gpt-oss) the system-message identity.

For each chosen idea, the referent dossier is taken verbatim from an earlier
run_fifteen.py run (so referent sampling noise is out of the comparison), the
deliberation prompt is rebuilt with DeliberationGate's own builder, and the
same deliberation call the gate makes (same system prompt, max_tokens,
temperature) is repeated --samples times under each identity. Identities
alternate within each idea so any drift over a long run lands on all
conditions equally. Identities only apply to gpt-oss (see backend.py);
other models run once per sample with their own chat template, recorded as
identity "none".

No checkpoints are proposed or committed — this only samples deliberations.
Resumable: (idea, identity, sample) triples already in results.jsonl are skipped.

Runs so far:
  gpt-oss identity repeat (2026-09-23):
    run_fixed_dossier.py --run-name 2026-09-23-gpt-oss-20b-identity-repeat
        --model gpt-oss-20b --samples 5 --ideas c2 t1 s2
        --identities template-default local-identity-v1
  Qwen3-32B, all fifteen, no identity (2026-09-23):
    run_fixed_dossier.py --run-name 2026-09-23-qwen3-32b-fifteen-fixed-dossier
        --model qwen3-32b --samples 1
  Qwen3-32B, c2 repeat (2026-09-24):
    run_fixed_dossier.py --run-name 2026-09-24-qwen3-32b-c2-repeat
        --model qwen3-32b --samples 5 --ideas c2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from actualizer.backend import GPT_OSS_IDENTITY_VERSION, LMStudioBackend  # noqa: E402
from actualizer.checkpoints.gate import (  # noqa: E402
    DeliberationGate,
    _DELIBERATION_SYSTEM_PROMPT,
    _parse_stance,
)
from actualizer.training import split_channels  # noqa: E402

EXPERIMENTS = ROOT / "state" / "experiments"
ALL_IDEAS = ["e1", "e2", "e3", "e4", "s1", "s2", "t1", "t2", "v1", "v2", "c1", "c2", "b1", "b2", "m1"]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run-name", required=True)
    p.add_argument("--model", required=True, help="LM Studio model identifier")
    p.add_argument("--samples", type=int, default=1)
    p.add_argument("--ideas", nargs="+", default=ALL_IDEAS)
    p.add_argument("--identities", nargs="+", default=[GPT_OSS_IDENTITY_VERSION],
                   help="gpt-oss only; ignored for other models")
    p.add_argument("--source-run", default="2026-09-23-gpt-oss-20b-fifteen-local-identity",
                   help="run_fifteen.py run whose dossiers are reused")
    p.add_argument("--timeout", type=int, default=3600)
    return p.parse_args()


def load_source(source_run: Path):
    """(idea_id -> (proposal, dossier)) from a run_fifteen.py run, matched by dossier_id."""
    rows = [json.loads(l) for l in (source_run / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    dossiers = {}
    for l in (source_run / "actualizer_audit.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(l)
        if e["kind"] == "referent_dossier":
            dossiers[e["payload"]["dossier_id"]] = e["payload"]
    return {r["id"]: (r["proposal"], dossiers[r["dossier_id"]]) for r in rows if r.get("dossier_id") in dossiers}


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    out = EXPERIMENTS / args.run_name
    out.mkdir(parents=True, exist_ok=True)
    results_path = out / "results.jsonl"
    done = set()
    if results_path.exists():
        for l in results_path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((r["id"], r["identity"], r["sample"]))

    source = load_source(EXPERIMENTS / args.source_run)
    missing = [i for i in args.ideas if i not in source]
    if missing:
        print(f"No dossier in {args.source_run} for: {missing}")
        return 1

    if "gpt-oss" in args.model.lower():
        backends = {name: LMStudioBackend(model=args.model, timeout=args.timeout, identity=name)
                    for name in args.identities}
    else:
        backends = {"none": LMStudioBackend(model=args.model, timeout=args.timeout)}
    if not next(iter(backends.values())).is_available():
        print("LM Studio server not reachable on :1234")
        return 1

    for idea_id in args.ideas:
        proposal, dossier = source[idea_id]
        prompt = DeliberationGate._build_deliberation_prompt(proposal, dossier)
        for sample in range(args.samples):
            for identity, backend in backends.items():
                if (idea_id, identity, sample) in done:
                    continue
                t0 = time.time()
                row = {"id": idea_id, "identity": identity, "sample": sample,
                       "model_id": backend.model_id, "dossier_id": dossier["dossier_id"],
                       "source_run": args.source_run}
                try:
                    # Same call DeliberationGate.propose_and_commit makes.
                    raw = backend.complete(
                        system_prompt=_DELIBERATION_SYSTEM_PROMPT,
                        user_prompt=prompt,
                        max_tokens=4000,
                        temperature=0.4,
                    )
                    ch = split_channels(raw)
                    stance = _parse_stance(raw)
                    row.update(
                        stance=stance.value if stance else None,
                        analysis=ch.get("analysis", ""),
                        final=ch.get("final", ""),
                        raw=raw,
                        error=None,
                    )
                except Exception as e:  # keep going; a failed sample is data too
                    row.update(error=f"{type(e).__name__}: {e}")
                row["seconds"] = round(time.time() - t0, 1)
                with results_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{idea_id} s{sample} {identity:18} {row.get('stance') or row.get('error')} {row['seconds']}s", flush=True)

    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
