# 03 — Classify reviews and propose modifications

**What to build:** Screen one candidate review at a time with the approved Stage 3 prompt and return a skip or every meaningful, actionable modification supported by that review.

**Blocked by:** 02 — Normalize the recipe and reviews

**Status:** ready-for-agent

- [x] Send the approved system rules and all 21 compact JSON example pairs with the normalized recipe and one candidate review.
- [x] Return a review-specific skip with a reason or actionable modifications grouped by the changes that must apply together.
- [x] Include verbatim evidence for each modification and label benefits as reported or inferred. Helpful votes can inform the decision when a change is grounded in the review.
- [x] Propose exact or calculable quantities, times, and temperatures, or observable cues where applicable. Represent relative ingredient calculations so validation can check them.
- [x] Use exact recipe IDs. Consolidate compatible changes to the same target, choose the better-supported alternative when needed, and order proposals as specified.
- [x] Verify skip, multi-modification, linked-edit, ambiguous-target, vague-quantity, and failed-response cases with a stub at the model provider. Keep persistent provider or response failures distinguishable from a semantic skip.
- [x] Classify eligible five-star candidates in Stage 2's globally vote-ranked order. A semantic skip advances to the next candidate; an operational failure remains failed after retries for that candidate.

**Verification note (2026-11-22):** The Stage 3 classifier uses the approved system rules and all 21 compact example pairs as role messages, followed by the normalized recipe and one candidate as the final user message. Stage 2 globally ranks eligible candidates by descending helpful votes, placing known counts before unknown and preserving normalized source order on ties. Stage 3 iterates that order: a semantic skip records its review ID, source, and model reason before advancing; the first proposal is returned. Provider/contract failure returns failed after up to two application retries (OpenAI SDK retries disabled) for that same candidate and does not advance. Malformed JSON/schema, mismatched review identity, and non-verbatim evidence are retried. Proposal, exhausted, and failed results carry `selected_review` metadata when a candidate was attempted, plus `skipped_reviews`; an empty pool returns null selected_review and an empty trace. The normal CLI exposes `python src/test_pipeline.py stage3 <saved-recipe.json>` with input/candidate progress on stderr and machine-readable JSON on stdout. Offline tests verify cross-source priority, ties, unknown counts, deduplicated vote merging, empty pools, skip-to-proposal fallback, all-skipped trace, persistent operational failure, proposal metadata, prompt structure, retry/fatal distinction, and CLI output/logging.

**Canonical ID correction (2026-11-22):** The 21 examples now use the Stage 2 conventions (`ingredient-000N` and `instruction-000N`) consistently in synthetic recipe rows and referenced targets/anchors. Before accepting a proposal, Stage 3 checks every target and anchor against exact IDs in the input recipe. A missing or unpadded reference enters the existing bounded response-contract retry path; Stage 3 does not rewrite or fuzzy-match IDs. Stage 4 remains responsible for independently routing and validating references.

[Pipeline spec](../spec.md)
