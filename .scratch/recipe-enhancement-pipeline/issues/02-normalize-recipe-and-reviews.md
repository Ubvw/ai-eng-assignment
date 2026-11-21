# 02 — Normalize the recipe and reviews

**What to build:** Turn a saved scraper payload into a normalized recipe with addressable ingredient lines and source steps, plus an ordered pool of review candidates.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [x] Preserve source recipe metadata and the exact wording and order of ingredients and instructions. Keep one editable step per source instruction entry.
- [x] Assign distinct, repeatable IDs within the same snapshot, including when two rows have identical text or two ingredients have similar names.
- [x] Parse ingredient name, exact quantity, and unit where supported. Preserve the original wording for partial or unknown parses, including qualifiers such as packed and softened.
- [x] Preserve full review text and available metadata, including helpful count. Assign local review IDs and keep the primary review distinct from featured tweaks.
- [x] Verify five-star eligibility and descending helpful-vote counts across both sources. Preserve input order for ties, put unknown counts after known counts, and include each unambiguously duplicated review once.
- [x] Verify the result from a saved Stage 1 payload and exercise fractions, missing fields, an absent primary, and an empty candidate pool.

[Pipeline spec](../spec.md)
