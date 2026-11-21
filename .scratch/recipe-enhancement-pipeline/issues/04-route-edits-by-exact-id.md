# 04 — Route edits by exact ID

**What to build:** Resolve each proposed edit to an exact ingredient line or source step and hand the resolved modification groups to validation.

**Blocked by:** 03 — Classify reviews and propose modifications

**Status:** ready-for-agent

- [x] Resolve replace and remove by exact target ID. Resolve insert by exact anchor ID and before or after position.
- [x] Set the recipe section from the resolved ID for both ingredients and instructions. Preserve each edit's modification and review context.
- [x] Return a diagnostic for an unknown or ambiguous target, missing anchor, or malformed operation. Keep unrelated modification groups available for validation.
- [x] Verify routing with similar sugar ingredients, targets in both sections, inserts before the first and after the last item, and unknown IDs and anchors.

**Verification note (2026-11-22):** `route_modifications` consumes the Stage 2 normalized recipe and Stage 3 proposal shape. Each fully valid modification is passed as a whole with its benefit/evidence, selected review, review ID, and edits annotated with the exact section/index/matched row. A group with any bad edit is omitted whole with a diagnostic; separate groups remain routable. IDs are matched as exact strings, including their padding. The offline CLI is `python test_pipeline.py stage4 <raw-recipe.json> <stage3-result.json>` (run from `src/`) and does not initialize a provider. The saved Ho Ho Cake Stage 3 result routes its two padded instruction edits and reports `ingredient-7` as unknown in the third group while preserving the other groups. Five Stage 4 unit tests pass.

[Pipeline spec](../spec.md)

**Held-out verification:** Ran the Stage 4 CLI on all 10 recipes with their saved Stage 3 proposals, using the fresh fallback proposals for the two previously skipped recipes. All 10 matched the expected routing outcomes. Stage 4 routed 25 of 26 modification groups and 52 edits. The one rejected group was the historical Ho Ho Cake proposal with an unpadded ingredient ID. See the [batch summary and result paths](../../../data/stage4_test/summary.json).
