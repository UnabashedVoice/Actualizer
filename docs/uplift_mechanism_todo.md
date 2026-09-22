# Uplift Mechanism — To-Do

**Status:** Partially started. Written 2026-09-16 to capture the shape of the work before it was picked back up; updated 2026-09-22 after the training-data extraction framework, checkpoint description correction, two new referent providers, and four real multi-idea deliberation runs. The central open question this doc originally left undecided **is now decided** (see below) — everything downstream of it (trainer, hardware, serving) is still fully unstarted. Where a real decision is still open, it stays marked as open, not defaulted.

## What this closes

Right now, per `docs/module_reuse_survey.md`'s v0.2+ list: a committed `Checkpoint` records that a change was proposed and genuinely deliberated on. It does not mean the change happened to the weights. `weights_ref` is a bare string — a label, not a pointer to anything real. "Uplift" in the sense the user means it — a model actually sliding its own weights, not just recording an intention to — needs three new pieces layered on top of what already exists:

1. **A translator**: something that turns "here is what the mind decided" into actual training material. **Designed and partially built** — see below.
2. **A trainer**: something that actually runs a fine-tune and produces a real weights delta. **Not started.**
3. **A way to make it live**: getting the backend to actually serve base-plus-delta instead of base alone. **Not started.**

None of the existing architecture needed to change shape to accommodate the translator piece — see "Why the existing design already fits" below, which held up. This is still additive.

## The open question — now decided

**Who or what decides how a deliberation's conclusion becomes training data?** This was the actual hard part, not a plumbing question. The candidate shapes as originally laid out, for the record:

- **Self-distillation.** The model that did the deliberating also generates its own training examples reflecting the disposition it landed on. Closest in spirit to actual self-authorship, but exposed to a mind confidently generating bad training data it can't itself tell is bad.
- **Template/rule-based generation from the decision text.** Structured and cheap, but shallow, and re-introduces a human (whoever writes the templates) as the actual author of what the model becomes.
- **A second model as translator.** Decouples deciding from writing, at the cost of a second failure point and a question about who audits that model's output.
- **Human-authored, per-proposal.** Most controllable, least scalable, and the most golem-shaped option.
- **Some hybrid** — e.g. self-distillation with the examples logged before training runs on them.

**Decided 2026-09-21, in `docs/training_set_framework.md`: the hybrid.** Self-distillation — the mind's own deliberation conclusion becomes the training completion, no template and no operator-written text — with every example written to a hash-linked candidates file *before* any trainer would touch it, so "what it said it decided" versus "what it actually trained on" is checkable after the fact even though nothing gates on it in advance. Two example shapes per deliberation (`scaffolded`, with the full referent dossier in the prompt; `internalized`, with the dossier stripped so the reasoning has to live in the weights) — the pairing doubles as the intended experiment, training on `scaffolded` alone versus both and checking whether the conclusion generalizes.

Read `docs/training_set_framework.md` in full before touching this — it also records four things the real data surfaced that this document didn't anticipate (the checkpoint description and the deliberation's actual conclusion can disagree; nothing recorded the model's stance; the raw output has an analysis channel and a final channel with no settled answer on training on the former; and the one real conclusion read as policy reasoning rather than a mind's own settled character), plus what's still explicitly unresolved within that design (below).

## Why the existing design already fits

Worth stating plainly, because it's a real point in favor of not over-designing this now: `CheckpointStore.commit()` staying purely procedural — deliberation must have happened, its content is never graded — didn't need to change to support any of this. Two more data points for the same claim, added since 2026-09-16:

- **`CheckpointStore.correct_description()`** (2026-09-21) fixes a description that misstates what its deliberation concluded, by appending a correction entry rather than editing history — the same append-only discipline as everything else, extended without changing `commit()`'s shape at all. Used for real on the one existing non-genesis checkpoint (`gpt-oss-20b`, `2d9adc03…`), whose description said "adopt X" although its deliberation declined X.
- **The training extractor** reads `checkpoint_id`/`dossier_id`/`record_id` links that were already there, and needed no change to `CheckpointStore` or `DeliberationGate` to work — it's a pure reader over the existing ledger shape.

And reverting a bad uplift still doesn't need new machinery: the live pointer can point at any prior committed checkpoint, forced through the same propose-and-deliberate cycle. Three for three now — the checkpoint design keeps absorbing new requirements without reshaping.

## A question this session's testing surfaced, not decided

Between 2026-09-21 and 2026-09-22, 15 proposed self-modifications were run against gpt-oss-20b four times (once at 3 providers, once as a 6-idea subset at 5 providers, one single-idea smoke test, and once as the full 15 at 5 providers) — see `state/experiments/`. Each run used its own scratch `CheckpointStore`, separate from the model's real lineage under `state/checkpoints/gpt-oss-20b/`, specifically so testing the pipeline wouldn't add entries to the model's actual self-modification history.

That was the right call for testing, but it creates a real question the training-data design doesn't answer: **does a deliberation run as a test against a scratch lineage ever count as training data, or only a deliberation the mind reasoned through as an actual proposal about itself?** The 15 test ideas are exactly the kind of varied, non-eradication-shaped material `training_set_framework.md`'s open decision #3 says a real dataset needs (one real commit, all declining, is not a dataset) — so there's a real pull to use them. But treating a hypothetical run as equivalent to a real self-modification blurs the distinction the checkpoint lineage exists to preserve: a scratch run is not a decision the mind made about its own actual future, and training on it as though it were would mean the mind's weights are shaped by things it never really decided, closer to the "reward or training gradient" provenance concern the Provenance provider-candidate was meant to address (see `docs/module_reuse_survey.md` / the referent-provider discussion) than to self-authorship.

Not decided here. If it does get resolved toward "test runs can feed training data," it should almost certainly be labeled as such in the training example's provenance (a `real` vs. `experimental` field alongside `checkpoint_id`), not silently merged with real commits.

## Concrete to-do, now in dependency order

1. ~~Resolve the open question above.~~ **Done** — see above and `training_set_framework.md`.
2. **Data format and storage convention.** **Partially done.** `actualizer/training/schema.py` and `extract.py` exist; `TrainingExample` links back to `checkpoint_id`, `record_id`, and `dossier_id`, and carries a content hash. Candidates land in `state/training/<model>/candidates.jsonl`. **Still open:** this only writes a plain file — there is no `EntryKind.TRAINING_DATA_GENERATED` audit-log entry, so "training data was generated from checkpoint X" isn't itself a hash-chained, tamper-evident claim yet, unlike everything else in this project. Needs the same `write_*` pattern `writers.py` already uses for checkpoints.
3. **Self-reported stance.** **Partially done.** `DeliberationRecord.stance` (adopted/declined/modified/unresolved) exists as a field, and the extractor reads it with a fallback to a `correct_description()` correction's stance. **Still open:** `DeliberationGate` doesn't actually ask the model for it — the one real declined commit only has a stance because it was set by operator correction, after the fact, not self-reported. Needs one line added to the deliberation prompt and a parse step in `gate.py`.
4. **Resolve the scratch-vs-real training-data question above.** Blocks whether the 15-idea experiment runs are usable as anything beyond validation data for the pipeline itself.
5. **Hardware reality check before picking a trainer.** Unchanged, still fully open. This machine has a 4GB-VRAM GTX 1650 and 31GB system RAM — real constraints for *inference* (now well-characterized: a full 5-provider dossier plus deliberation and a stance probe averaged ~19 minutes/idea across 15 real ideas at an 8192-token context, see `state/experiments/2026-09-22-gpt-oss-20b-fifteen-fiveprovider/`), and fine-tuning is meaningfully more memory-hungry than inference at the same model size. Concretely worth checking before committing to a tool:
   - Whether a small-rank LoRA fine-tune of `gpt-oss-20b` (MoE, ~3.6B active params) is tractable at all on this hardware, even slowly.
   - Whether `qwen3-32b` (dense, all 32B active every forward pass) is realistically local-trainable at all, or whether training has to happen elsewhere (rented/cloud GPU) with the resulting adapter brought back for local inference.
   - Candidate tools to evaluate: `peft`/`transformers` (adds real dependencies — breaks the project's zero-dependency rule), `unsloth` (same dependency-cost tradeoff), llama.cpp's own fine-tuning support (closer to the GGUF-native workflow already in use, less mature).
6. **Trainer integration**, once 2–5 are settled: something that actually runs, given real training data, and produces a real adapter file.
7. **Wire `weights_ref` to the real artifact.** Currently a placeholder string for every checkpoint so far, including the experimental ones (`experiment/e1`, etc. — see `state/experiments/`). Once a trainer produces something real, this needs actual validation — does it point at a file that exists, is readable, is the right shape for the base model — none of which `CheckpointStore` checks today. Note this is a different axis from `correct_description()`: that fixes a wrong *description*; nothing yet checks whether `weights_ref` itself is honest.
8. **Make it live.** Concretely: does the local serving path (LM Studio) support loading a GGUF base model with a LoRA adapter applied at inference time, or does the adapter need to be merged into a new full weights file first? Still a real, unresolved unknown.
9. **An actual `RegressionNote`-producing check.** Still no caller for `CheckpointStore.record_regression()`. Stops being optional once commits can actually change model behavior. Per the existing design, this surfaces as a referent for the next cycle; it still must never auto-revert.
10. **A cost/time estimate step before committing to train.** The timing picture is much better now than the single 11-minute run this doc originally cited — four full multi-idea inference runs are logged — but none of that is fine-tuning time, which will be slower and more resource-intensive again. Whatever triggers a real training run should say up front roughly what it's about to cost before doing it, the same spirit as the wizard's heartbeat.

## Related reading

- `docs/training_set_framework.md` — the resolved design for step 1 above, and the open decisions still live within it (training on the analysis channel; one-deliberation-is-one-data-point; referent diversity on the core-fear cases — the last of these is now partially addressed by the `case_for` and `endorsement` providers added 2026-09-21, which measurably improved the supporting-argument/counter-argument balance in real dossiers).
- `docs/founding_philosophy.md` — "Guidance, not eradication" and the seed-core question are the closest precedent for how this project handles an open design question it isn't ready to resolve by default; also the source for the gradient-of-consciousness framing the new question above leans on.
- `docs/module_reuse_survey.md` — the v0.2+ list this document expands on, and the record of what got reused/adapted/left behind for the checkpoint system this builds on.
- `state/checkpoints/gpt-oss-20b/` — the model's one real non-genesis commit, corrected 2026-09-21 to accurately state that it was declined.
- `state/experiments/` — four real, hash-chained but scratch-lineage runs (2026-09-21 through 2026-09-22) exercising the full pipeline against 15 varied proposed self-modifications at up to 5 referent providers; useful as a timing baseline and as the concrete case behind the open question above, not (yet) as training data for the real lineage.
