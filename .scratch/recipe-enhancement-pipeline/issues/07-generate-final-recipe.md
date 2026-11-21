# 07 — Generate the final recipe

**What to build:** Produce the final recipe JSON from the applied result, with a review evidence trail or a clear unchanged outcome.

**Blocked by:** 06 — Apply validated edits

**Status:** ready-for-agent

- [x] Generate a complete enhanced recipe with the changes that were actually applied and their before and after text where applicable.
- [x] For each applied modification, identify the source review, include its verified verbatim evidence, and distinguish reported from inferred benefits.
- [x] Return the original recipe with an unchanged outcome and a reason when candidate processing ends without an applicable edit.
- [x] Give an unexpected run failure a distinct outcome so it is visible in the final result.
- [x] Verify an enhancement with independent ingredient and instruction changes, a partial validation result, an unchanged recipe, and a failed run at the output boundary.

[Pipeline spec](../spec.md)

## Comments

- Run `stage7 <stage6-result.json>` offline. A result requesting the next review has status `continue` and exits with code 3. The caller is responsible for resuming candidate processing.
- All 57 offline tests passed, including six Stage 7 tests. Replaying Stage 5 through Stage 7 on the 10 saved held-out routing results produced 17 enhancement groups with 39 applied edits. Each published quote matched its source review verbatim. The CLI output matched the generated JSON for recipe 9397 with model credentials disabled.
