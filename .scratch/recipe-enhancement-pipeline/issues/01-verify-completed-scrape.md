# 01 — Verify the completed scrape

**What to build:** Verify the finished scraper's saved JSON handoff using a representative recipe with multiple ingredient lines, multiple source steps, and review candidates. Keep a saved output as a fixture for the loader and assemble the 15-recipe development set under `data/training_data/`.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [x] Capture one real output from the completed scraper and verify the recipe ID, title, and ordered ingredient and instruction string arrays.
- [x] Confirm the handoff exposes prep time, cook time, total time, servings, and yield, with absent values represented as supplied by the scraper.
- [x] Confirm the most helpful positive review is a single object or null and featured tweaks are an array of up to 10 items in source order.
- [x] Confirm review records carry text, rating, username, and helpful count, with date present when available.
- [x] Verify a saved edge case with a missing primary review and an empty featured list. Keep the representative scrape available to downstream verification.
- [x] Build the development set from the six existing recipe IDs and nine additional distinct recipes. Reuse a current Stage 1 capture where available and refresh legacy inputs with the completed scraper.
- [x] Save 15 current Stage 1 JSON payloads under `data/training_data/`. Verify that the recipe IDs are unique and have no overlap with the 10 held-out recipe IDs.

[Pipeline spec](../spec.md)


## Verification

Captured one bounded live scrape of Allrecipes recipe 10813 at `.scratch/recipe-enhancement-pipeline/fixtures/stage-1/recipe_10813_live.json` (11 ingredients, 9 instructions, all five metadata keys present, one primary review, 10 featured tweaks). Saved `.scratch/recipe-enhancement-pipeline/fixtures/stage-1/recipe_10813_missing_reviews_edge.json` as a derived edge payload with the primary set to null and the featured list empty. Local assertions passed for the live payload contract and the writer's null/empty review boundary; source inspection confirmed optional metadata/date fields are emitted as null/omitted when unavailable. No scraper code was changed. No batch evaluation or LLM API was used.

## Development set completion

Saved exactly 15 current Stage 1 payloads under `data/training_data/`. Reused the live 10813 capture and refreshed the other five existing recipe IDs through the scraper, then scraped nine additional public recipe pages. Verified all payloads have the current handoff shape, IDs are unique and match the intended set, and none overlap the held-out inputs. IDs: 10402, 10813, 12682, 14231, 144299, 14685, 19117, 20144, 21014, 23600, 26317, 284494, 45613, 77935, 86662. No product code, held-out data, or baseline data was changed.