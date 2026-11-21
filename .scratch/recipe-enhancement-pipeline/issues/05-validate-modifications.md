# 05 — Validate modifications

**What to build:** Produce a validated plan and verified review evidence. Keep independent valid modifications available and surface each rejected modification for diagnosis.

**Blocked by:** 04 — Route edits by exact ID

**Status:** needs-triage

- [x] Check operation requirements, references, and exact review quotes against the source snapshot and originating review.
- [x] Verify relative arithmetic and exact changed values. Reject negative quantities, unsupported conversions, and unspecified numeric changes. Accept a clear observable cue when it is actionable.
- [x] Reject a removal or substitution that leaves a clear dangling reference in an instruction. Accept coordinated edits together when they resolve it.
- [x] Accept or reject each modification as a unit. Keep unrelated valid modifications when another group fails.
- [x] On residual conflicts, keep the first valid modification in proposal order and log the kept and rejected modification IDs and target.
- [x] Log rejections with review ID, modification ID, target when available, and reason. Advance to the next ranked eligible review when a review yields no applicable modification. Return an empty plan for an unchanged result once the candidate pool is exhausted.
- [x] Verify exact and unverified quotes, valid and invalid arithmetic, linked changes, partial acceptance, conflict selection, console diagnostics, fallback, and an exhausted pool using saved routed proposals.

[Pipeline spec](../spec.md)

## Comments

- Implemented Stage 5 as `validate_modifications(raw_recipe, stage4_result)` and added offline `stage5 <raw-recipe.json> <stage4-result.json>` CLI support. The CLI returns JSON status `continue` and exit code 3 with the next ranked candidate when all groups for the current review fail; it does not invoke a provider. Exhaustion is a successful `empty` plan, distinct from `failed` input/contract status.
- Verification: 9 Stage 5 tests passed. Combined offline suite `..\\.venv\\Scripts\\python.exe -m unittest test_stage5_validation test_stage4_routing test_normalization test_stage3_classification` passed (42 tests). Saved Stage 4 batch smoke validated groups for all 10 held-out inputs; Ho Ho Cake retained one valid group and two diagnostics.
- Validation uses Stage 2's existing exact quantity parser and `Fraction`; it accepts arithmetic only when source/replacement units match and does not guess cross-unit conversions. Instruction number changes must be supported by a matching exact numeric value in the review quote; observable cue edits without numeric changes remain valid. Dangling references are detected by exact normalized ingredient-name mentions, so aliases and paraphrases are intentionally not inferred.
