# 06 — Apply validated edits

**What to build:** Apply the validated plan to a working copy and return the complete resulting recipe with a record of each edit that actually took effect.

**Blocked by:** 05 — Validate modifications

**Status:** ready-for-agent

- [x] Apply replace, remove, and insert to ingredients and source steps using their resolved IDs. Keep insertion order deterministic and preserve unrelated recipe content.
- [x] Keep the source recipe intact. Apply the accepted plan as grouped and retain review and modification references for the result.
- [x] Record the actual operation, section, target, and before and after text where applicable.
- [x] Fail the run and log the failed operation if applying a validated edit fails unexpectedly.
- [x] Verify successful ingredient-only, instruction-only, and mixed plans. Simulate a failure after an earlier edit and verify the source remains intact and the run reports failure.

[Pipeline spec](../spec.md)

## Comments

- Apply a validated plan offline with `stage6 <raw-recipe.json> <stage5-result.json>`. Output includes the complete resulting recipe on success, before and after text where applicable, and each modification's verified review evidence and actual changes.
- All 51 offline tests passed, including nine Stage 6 tests. The CLI applied 17 modification groups with 39 edits across all 10 saved held-out inputs. The checks verified the recorded text, review, and unchanged source and unrelated content. The saved plans contained replacements and insertions. The focused tests also covered removals and failure after a preceding edit.
