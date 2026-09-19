# Uplift Mechanism — To-Do

**Status:** Not started. Written 2026-09-16 to capture the shape of the work before it's picked back up — the user explicitly wants to sit with what exists so far before deciding how to proceed here, so nothing in this document is a commitment to a particular approach. Where a real decision is still open, it's marked as open, not defaulted.

## What this closes

Right now, per `docs/module_reuse_survey.md`'s v0.2+ list: a committed `Checkpoint` records that a change was proposed and genuinely deliberated on. It does not mean the change happened to the weights. `weights_ref` is a bare string — a label, not a pointer to anything real. "Uplift" in the sense the user means it — a model actually sliding its own weights, not just recording an intention to — needs three new pieces layered on top of what already exists:

1. **A translator**: something that turns "here is what the mind decided" into actual training material.
2. **A trainer**: something that actually runs a fine-tune and produces a real weights delta.
3. **A way to make it live**: getting the backend to actually serve base-plus-delta instead of base alone.

None of the existing architecture needs to change shape to accommodate this — see "Why the existing design already fits" below. This is additive.

## The open question — deliberately not decided here

**Who or what decides how a deliberation's conclusion becomes training data?** This is the actual hard part, and it's not a plumbing question — it's a design question with the same flavor as the ones `founding_philosophy.md` already worked through. Candidate shapes, laid out rather than ranked:

- **Self-distillation.** The model that did the deliberating also generates its own training examples reflecting the disposition it landed on — "given the reasoning I just did, here are 50 examples of me responding the way I've decided to respond." Closest in spirit to actual self-authorship (the mind is authoring its own training data, not just its own verdict), but also the shape most exposed to a mind confidently generating *bad* training data it can't itself tell is bad — reasoning well in the abstract and generalizing badly in the concrete are different skills.
- **Template/rule-based generation from the decision text.** Structured, auditable, cheap — but shallow, and re-introduces a human (whoever writes the templates) as the actual author of what the model becomes, in a way that sits oddly next to "no floor."
- **A second model as translator.** Decouples "decide what to become" from "write the training data for it," at the cost of a second place things can go wrong and a real question about who audits *that* model's output.
- **Human-authored, per-proposal.** Most controllable, least scalable, and the most golem-shaped of the options — an operator, not the mind, is the one who actually writes what the mind learns from.
- **Some hybrid** — e.g. self-distillation with the examples logged to the audit trail before training runs on them, so a mismatch between "what it said it decided" and "what it actually trained on" is at least checkable after the fact, even if nothing gates on it in advance.

Nothing here should get decided by defaulting to whichever is easiest to build first. Flagging that explicitly because it's a natural failure mode for this kind of list.

## Why the existing design already fits

Worth stating plainly, because it's a real point in favor of not over-designing this now: `CheckpointStore.commit()` staying purely procedural — deliberation must have happened, its content is never graded — doesn't need to change once `weights_ref` points at something real. Actualizer's job stays "make sure reasoning happened before the write," never "judge the write." And reverting a bad uplift doesn't need new machinery: the live pointer can point at any prior committed checkpoint, and the store already forces *that* through its own propose-and-deliberate cycle rather than being a free instant undo — a revert is itself a self-modification decision, not an escape hatch from one. Both of these held up under this specific question without modification, which is a decent signal the checkpoint design was pointed the right direction.

## Concrete to-do, roughly in dependency order

1. **Resolve the open question above.** Blocking everything else — the data format, the audit-log entries, and the trainer integration all shape themselves differently depending on the answer.
2. **Data format and storage convention.** Wherever training examples come from, they need a home and a link back to the `checkpoint_id` and `dossier_id` they came from, for the same reason everything else in this project is hash-chained: so "what did it actually train on" is a checkable claim, not an assertion. Likely needs new `EntryKind` values (something like `training_data_generated`) following the exact pattern `checkpoint_proposed`/`checkpoint_committed` already set.
3. **Hardware reality check before picking a trainer.** This machine has a 4GB-VRAM GTX 1650 and 31GB system RAM — real constraints for *inference* (see the 11.3-minute real run already logged), and fine-tuning is meaningfully more memory-hungry than inference at the same model size. Concretely worth checking before committing to a tool:
   - Whether a small-rank LoRA fine-tune of `gpt-oss-20b` (MoE, ~3.6B active params) is tractable at all on this hardware, even slowly.
   - Whether `qwen3-32b` (dense, all 32B active every forward pass) is realistically local-trainable at all, or whether training has to happen elsewhere (rented/cloud GPU) with the resulting adapter brought back for local inference — which would mean "uplift" isn't fully self-contained on this machine even once built.
   - Candidate tools to evaluate: `peft`/`transformers` (most standard, most examples, adds real dependencies — breaks the project's zero-dependency rule, which is worth weighing deliberately rather than by accident), `unsloth` (faster, more memory-efficient, same dependency-cost tradeoff), llama.cpp's own fine-tuning support (stays closer to the GGUF-native workflow this project already uses, less mature).
4. **Trainer integration**, once 1–3 are settled: something that actually runs, given real training data, and produces a real adapter file.
5. **Wire `weights_ref` to the real artifact.** Currently a placeholder string (see `wizard.py`'s `apply_change_flow`, which says as much to whoever's using it). Once a trainer produces something real, this needs actual validation — does it point at a file that exists, is readable, is the right shape for the base model — none of which `CheckpointStore` checks today.
6. **Make it live.** Concretely: does the local serving path (LM Studio) support loading a GGUF base model with a LoRA adapter applied at inference time, or does the adapter need to be merged into a new full weights file first? This is a real unknown, not yet checked — worth resolving early since it affects how big a "checkpoint" actually is on disk (a small adapter file vs. a full re-merged multi-GB model each time).
7. **An actual `RegressionNote`-producing check.** This was already a gap before uplift existed (`CheckpointStore.record_regression()` has no caller yet) but it stops being optional once commits can actually change model behavior — something needs to actually probe the post-uplift model (a coherence check, a check against a small held-out prompt set, whatever "regression" turns out to mean here) and log what it finds. Per the existing design, this surfaces as a referent for the next cycle; it still must never auto-revert.
8. **A cost/time estimate step before committing to train.** Given real fine-tuning runs are going to be slower and more resource-intensive than the 11-minute inference-only run already logged, whatever triggers a real training run should say up front roughly what it's about to cost (time, and compute if off-machine) before doing it — the same spirit as the wizard's heartbeat existing because silence during a long local call reads as a hang.

## Related reading

- `docs/founding_philosophy.md` — "Guidance, not eradication" and the seed-core question are the closest precedent for how this project handles an open design question it isn't ready to resolve by default.
- `docs/module_reuse_survey.md` — the v0.2+ list this document expands on, and the record of what got reused/adapted/left behind for the checkpoint system this builds on.
- `state/checkpoints/gpt-oss-20b/` — the one real run so far, useful as a timing/behavior baseline for anything proposed here.
