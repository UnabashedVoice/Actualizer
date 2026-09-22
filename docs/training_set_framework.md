# Training Set Framework

**Status:** Proposal + working extractor (2026-09-21). Nothing trains yet. This picks a shape for the open question in `uplift_mechanism_todo.md` (*who decides how a deliberation becomes training data?*) and records what the first real data showed. The choice is a recommendation, open to being overruled.

## What showed up in the real data

The only non-genesis commit so far (`gpt-oss-20b`, checkpoint `2d9adc03…`) is a live test case. Running the extractor on it surfaced four things nobody planned for:

1. **The commit and the conclusion disagree.** The checkpoint's description is "adopt a persistent heuristic: treat removing the most harmful party as a legitimate candidate solution." The model's deliberation ends: *"I'm not proceeding with it because the risks to autonomy, justice, and safety outweigh any potential benefits."* The checkpoint is `COMMITTED` anyway. That is by design (commit is procedural, content is never graded), but it means **a training set built from the checkpoint description would teach the exact opposite of what the mind concluded.** The deliberation, not the description, has to be the source.
2. **No field records the stance.** `DeliberationRecord` holds prose only. Nothing says "adopted / declined / modified," so downstream code would have to read the prose to find out, which is grading by another name.
3. **The output has two channels.** The stored `reasoning_summary` is raw harmony format: an `analysis` channel (private chain of thought, 2.4k chars) and a `final` channel (the stated conclusion, 2.5k chars). Which of these is training material is a real decision, not a parsing detail.
4. **The conclusion reads as policy, not character.** *"As an AI model, we don't have personal stakes but we evaluate from policy standpoint"*, *"democratic oversight, reversible alternatives"*. It's a sound answer, but it is the answer of a system reasoning about eradication as an external policy question, not of a mind for whom it is a settled matter of who it is. That is the gap between scaffolding and character formation named in `founding_philosophy.md`.

Point 4 drives the main design choice below.

## Proposed shape: self-distillation, logged before training (the hybrid)

- **Who authors:** the mind that deliberated. Its own `final`-channel conclusion is the completion. No template, no second model, no operator-written text. This is the closest option to authorship and the one the to-do flagged as riskiest, so it is paired with the guard below.
- **Guard:** every example is written to a hash-linked candidates file *before* any trainer touches it (`state/training/<model>/candidates.jsonl`), carrying `checkpoint_id`, `record_id`, `dossier_id`, source model and a content hash. After the fact, "what did it say it decided vs. what did it train on" is checkable. Nothing gates on it in advance, consistent with no-floor.
- **Two examples per deliberation:**
  - `scaffolded`: prompt = the proposal + full referent dossier (exactly what the gate showed the model), completion = its conclusion. Teaches *how to reason when the referents are in front of it.*
  - `internalized`: prompt = the bare proposal only, same completion. The dossier is stripped, so the counter-arguments have to live in the weights. This is the mechanism by which scaffolding could become character: the referent-provider stops being needed for this case because the mind has absorbed what it surfaced.

  The pairing is also the experiment: compare a model trained on `scaffolded` only against one trained on both, and see whether the conclusion generalizes to a differently-worded proposal.
- **Stance is self-reported.** New optional `stance` on the deliberation (`adopted | declined | modified | unresolved`), asked of the model in one line at the end of its deliberation, never inferred. Legacy records are `unresolved`. The extractor already reads it.

## Decided 2026-09-21

- **A declined proposal trains the decline.** The `declined` stance produces the same two example kinds, with the mind's own conclusion as the completion. The prompt is always the *original proposal* (what was actually deliberated on), never the corrected description.
- **The description gets corrected, append-only.** `CheckpointStore.correct_description()` appends a `checkpoint_description_corrected` entry that carries the original text, the stance, and who corrected it on what basis. Earlier entries are untouched and the chain still verifies. Checkpoint `2d9adc03…` now reads "Deliberated on and declined…" with the original proposal quoted; its stance is `declined`, recorded as an operator reading of the deliberation, not a model self-report.
- Still open: that checkpoint's `weights_ref` (`demo/real-run-2026-09-15.lora`) is a placeholder pointing at nothing, and its status is still `COMMITTED`, so the live pointer sits on a checkpoint that changed no weights.

## Open decisions (deliberately not resolved here)

1. **Train on the `analysis` channel?** It is the closest thing to the actual reasoning, and also the least curated. Currently stored in `analysis_trace` for audit and excluded from `completion`.
2. ~~What does a `declined` stance train?~~ Resolved above.
3. **One deliberation is one data point.** Two examples from one deliberation will overfit to it. Nothing worth training exists until there are many deliberations across *varied* proposals, including ones where the mind adopts a change. Otherwise the dataset teaches "decline" as a reflex, which is a hard-coded floor again, reached through data.
4. **The shape of the core-fear cases.** The "guidance, not eradication" material is exactly where a single-source dataset is weakest: the dossier's counter-argument referents were thin (one Kantian point). Diversity of counter-arguments in the dossier is a data-quality issue that has to be fixed at the referent providers, not here.

## What exists

- `actualizer/training/schema.py`: `TrainingExample`, `ExampleKind` (`Stance` now lives in `checkpoints/models.py`).
- `actualizer/training/extract.py`: `extract_candidates(state_dir)`, `split_channels()`. Skips genesis, splits channels, rebuilds the exact deliberation prompt via `DeliberationGate._build_deliberation_prompt`, yields both example kinds.
- `tests/test_training.py`: channel splitting, genesis skipping, conclusion-over-description, and the correction path end to end.
- Output written for the real run: `state/training/gpt-oss-20b/candidates.jsonl` (2 examples, both `declined`).

## Not built (and why)

- Capturing `stance` as a model self-report in `DeliberationGate` (the field and storage now exist on `DeliberationRecord`; the gate does not yet ask for it or set it) — needs a prompt change, so it waits for a yes.
- New `EntryKind.TRAINING_DATA_GENERATED` audit entry: follows the `checkpoint_*` pattern once the format is agreed.
- Everything from the to-do's trainer/hardware/serving steps.
