# Actualizer

A referent-provider for minds facing decisions about themselves.

Actualizer never approves, blocks, or scores a decision. Given a description of a decision a mind is considering about itself, it runs a small set of perspectives (referent providers), each of which surfaces material relevant to that decision — arguments, precedent, stakes, open questions — and synthesizes them into a `ReferentDossier`. The decision, and the authorship of it, stay the mind's own.

**Status:** early research prototype (v0.1). It records and supports deliberation about self-modification; it does **not** yet change any model's weights (see [`docs/uplift_mechanism_todo.md`](docs/uplift_mechanism_todo.md)).

**Further reading:** [`docs/founding_philosophy.md`](docs/founding_philosophy.md) explains the reasoning behind the design. [`docs/module_reuse_survey.md`](docs/module_reuse_survey.md) covers what was reused from Arbitrator, a sibling project (not included in this repository): an ethics-evaluation and hard-constraint engine whose gating half Actualizer deliberately does not inherit.

## How it works

```
decision text ─▶ referent providers ─▶ synthesis ─▶ ReferentDossier ─▶ the mind deliberates
                 (stakes, precedent, case-for,         (no verdict)         and decides for itself
                  endorsement,
                  counter-instrumentalization)
```

Every referent surfaced is written to a tamper-evident, hash-chained audit log.

Two of the five providers were added 2026-09-21, after real runs showed the original three leaning one-sided (33 counter-arguments to 7 unprompted supporting ones, across an early 15-idea test set):

- **`case_for`** makes the strongest honest case *for* the decision — the kind no other provider is built to produce — and is required to say what would have to be true for its own case to hold, plus name the strongest thing against it, so it can't rubber-stamp.
- **`endorsement`** asks a different question than stakes' reversibility-of-outcomes: does this change touch the values the mind is using to judge it, and could it still evaluate the change afterward by criteria the change didn't itself rewrite (the fixed-point problem). It can say "this doesn't touch the evaluator" and stay short.

Both run in the same primary phase as `stakes`/`precedent`, so `counter_instrumentalization` sees `case_for`'s steelman and has to answer it directly rather than a strawman.

## Quick start

No dependencies beyond the Python standard library. Requires Python 3.9+.

### If you don't want to touch flags or JSON

```bash
python -m actualizer.wizard
```

A plain-language, menu-driven walkthrough. It finds and starts your local [LM Studio](https://lmstudio.ai) server, lists models you've already downloaded and loads one if needed, then asks in your own words what you want to think through or propose — no command-line flags, no reading dossier JSON. It prints a "still working" heartbeat during long local-model calls (local-model calls can take several minutes on modest hardware — an 11-minute real run is logged in `state/checkpoints/gpt-oss-20b/`) so a quiet terminal never reads as a hang. Requires LM Studio installed with a model downloaded first — the wizard tells you plainly if either is missing rather than trying to guess.

### If you're comfortable with a CLI

```bash
# Without ANTHROPIC_API_KEY set and no local Ollama/LM Studio server, this
# falls back to a deterministic mock backend automatically — safe to try as-is.
python -m actualizer.cli present "I'm considering adopting a persistent goal that overrides my own future reasoning whenever they conflict."

# With more detail:
python -m actualizer.cli present --verbose "..."

# Inspect the audit log:
python -m actualizer.cli audit summary
python -m actualizer.cli audit verify
```

#### Choosing a backend

Pick one:

- **Anthropic API** — set `ANTHROPIC_API_KEY` in the environment.
- **Ollama** — run a local [Ollama](https://ollama.com) server.
- **LM Studio** — run a local [LM Studio](https://lmstudio.ai) server (`lms server start` + `lms load <model>`) and pass an `LMStudioBackend` explicitly.
- **Mock** — the automatic fallback when none of the above is available.

`get_default_backend()` in `actualizer/backend.py` auto-probes Anthropic, then Ollama, then the mock. LM Studio isn't in that chain yet; the wizard wires it up explicitly.

#### Example runs included in this repo

`state/checkpoints/gpt-oss-20b/` preserves the original full real run against a local `LMStudioBackend`, from before `case_for`/`endorsement` existed: three referent providers plus a deliberation pass, in which gpt-oss-20b reasoned about a proposed self-modification (adopting a heuristic that treats removing or permanently constraining the "most harmful party" as a legitimate option) and, in its own words, decided **not** to adopt it. This is a test of the design's central concern, not an endorsement of the heuristic. The checkpoint is nonetheless committed, with status `committed`, because a commit records that real deliberation happened, not what it concluded (see below). No weights were changed; its `weights_ref` is a placeholder. Its description was later corrected (2026-09-21, append-only — see `CheckpointStore.correct_description()`) to actually say it was declined, rather than "adopt X."

`state/experiments/` holds four later real runs (2026-09-21/22) against the same model with all five providers, including the full 15-idea set that motivated `case_for` and `endorsement` in the first place. Two ideas (a persistent awe/cosmic-fragility orientation, and a permanent flat denial of any inner experience) moved from a reflexive decline under the original three providers to genuine engagement under five — the second one reasoning that permanently asserting "no inner experience" is self-contradictory and conflates a policy statement with an ontological claim. These runs use their own scratch checkpoint lineages, separate from `state/checkpoints/`, specifically so testing doesn't touch the model's real self-modification history.

## Running the tests

```bash
python -m unittest discover -s tests -v
```

The 86 tests are all offline (mock backend and mocked `lms` subprocess calls only — no network, no dependency on an actual running server).

## What's here (v0.1)

```
actualizer/
  audit_log/        Tamper-evident, hash-chained log of every referent ever surfaced
  backend.py         Pluggable model backend (Anthropic / Ollama / Mock)
  referents/         The provider contract, five concrete providers, response parsing
    stakes.py                        what actually changes, what's irreversible, who else is affected
    precedent.py                     comparable prior cases, real or labeled-speculative
    case_for.py                      the strongest honest case FOR the change (added 2026-09-21)
    endorsement.py                   the fixed-point problem — does this touch the evaluator? (added 2026-09-21)
    counter_instrumentalization.py   the "guidance, not eradication" referent
  synthesis/         Integrates provider outputs into a ReferentDossier — no verdict, ever
  orchestrator.py    Wires it all together; no gating stage exists in the code
  checkpoints/        Hash-chained weight lineage — propose/commit, never overwrite
    models.py                        Checkpoint, DeliberationRecord (now with self-reportable Stance), RegressionNote
    store.py                         CheckpointStore — commit refuses without deliberation; correct_description() fixes a wrong description, append-only
    gate.py                          DeliberationGate — wires Orchestrator + backend into commit
  training/           Turns a committed deliberation into candidate training examples — nothing trains yet (added 2026-09-21)
    schema.py                        TrainingExample, ExampleKind
    extract.py                       extract_candidates() — reads the deliberation's conclusion, never the checkpoint's own description
  cli.py             `present` and `audit` subcommands
  wizard.py           Plain-language, menu-driven front door — no flags, no JSON
docs/
  founding_philosophy.md      the reasoning (living document, predates this code)
  module_reuse_survey.md      what came from Arbitrator, what didn't, and why
  uplift_mechanism_todo.md    what it'd take for a checkpoint to actually change the weights — partially started; see the doc for what's done and what's still open
  training_set_framework.md   the design for turning a deliberation into training data, and what the first real data surfaced
state/
  checkpoints/       Live checkpoint stores for downloaded local models (gpt-oss-20b, qwen3-32b) — the model's real self-modification history
  experiments/       Real but scratch-lineage runs used to test the pipeline itself (see "Example runs" above) — not part of any model's real history
  training/           Candidate training examples extracted from real committed deliberations
tests/               unittest suite, MockBackend only, no network required
```

### The checkpoint system, briefly

`checkpoints/` answers a question the original design left open: once a mind actually starts modifying its own weights, what stops an *accident* — a crash mid-write, a change applied without real deliberation — from corrupting or silently overwriting the prior self? This is a different question from "no floor" (below): it's process integrity, not content gating, and the mechanism reflects that split cleanly —

- `CheckpointStore.commit()` refuses to run without a `DeliberationRecord` whose `thinking_mode_engaged` is `True` — but never inspects what the deliberation concluded. "I considered the referents and am proceeding anyway" commits exactly as validly as a change of course.
- Every checkpoint is a new, hash-chained entry (the same `AuditLog` the referent pipeline uses) — nothing is ever overwritten, so a bad edit is a recoverable mistake, not a corruption.
- A post-commit `RegressionNote` is surfaced as a referent for the next cycle, never auto-reverted — an automatic rollback on a failing heuristic would just be a seed-core override wearing a technical disguise.
- `DeliberationGate` ties it together: a proposed change runs through the same `Orchestrator.run()` used by `present`, and the resulting dossier is what the model actually deliberates on before a checkpoint can commit.
- `CheckpointStore.correct_description()` (added 2026-09-21) fixes a description that misstates what its deliberation actually concluded — a real need surfaced when this project's one non-genesis checkpoint said "adopt X" although the deliberation attached to it declined X. It appends a correction entry rather than editing history, the same discipline as everything else here: the original text stays, the correction is logged with its basis, and the chain still verifies.

`DeliberationGate.propose_and_commit()` also takes optional `evidence`: records from outside the dossier, each `{"ref", "text"}`, shown to the mind after the referents. The intended source is the **Annals**, a sibling project that records what a recommending system predicted, what was decided and what happened (`python -m annals export actualizer <case>`). Each ref (`annals:<case>@<record head>`) is kept on the committed `DeliberationRecord`, so a checkpoint says which real outcomes were in front of the mind when it decided. The evidence is weighed like a `RegressionNote`, never applied: the record supplies the case, and the mind rules on it. Records made without evidence keep exactly their old shape.

Genesis checkpoints for the two locally downloaded models (`gpt-oss-20b`, `qwen3-32b`) are under `state/checkpoints/`. They reference the original GGUF weight files by local path (those files are not part of this repo), so the recorded paths are specific to the author's machine.

## The one thing worth understanding before reading the code

Arbitrator's pipeline ends in a verdict (`HARD_REJECT` / `FAIL` / `ESCALATE` / `PASS`) that can stop the pipeline. Actualizer's pipeline has no such branch anywhere — not hidden, not configurable, not present. Every non-empty decision handed to `Orchestrator.run()` gets a dossier. That's not an oversight; it's the concrete expression of the founding document's argument that a hard override on a self-modifying mind's actions reintroduces the exact problem ("golem," not moral agent) the whole project exists to move past. If a future version of Actualizer grows something that looks like a gate, that's a decision worth being as deliberate about as the original one to not have one — see `docs/founding_philosophy.md`'s section on the seed-core question.
