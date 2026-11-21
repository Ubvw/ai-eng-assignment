# Recipe enhancement pipeline

**Status:** ready-for-agent

## Problem Statement

Recipe reviews can suggest improvements, but the current pipeline can miss useful reviews, choose the wrong ingredient or step, or return a change whose reasoning is difficult to verify. The completed scraper provides the site's most helpful positive review and featured tweaks. The pipeline needs to check eligible reviews in helpful-vote order, propose all meaningful changes in the first review that yields an applicable modification, and show exactly which part of the review supports each applied change.

The product needs an exact, usable recipe and an honest outcome when the candidate pool produces no applicable changes. The maintainer needs a way to verify every stage as it lands and compare the finished pipeline with the current baseline.

## Solution

Build the pipeline around seven independently verifiable stage boundaries. Use the finished scraper as the input source. Normalize recipe lines, rank the eligible reviews by helpful votes, and evaluate them in that order. Route and validate proposed edits by exact IDs, apply the validated plan, and generate an enhanced or unchanged recipe with a traceable outcome.

A recipe uses one selected review. Independent valid modifications can proceed when another fails. Coordinated edits within one modification succeed or fail together. An enhancement includes only changes that were actually applied, the benefit that motivated them, and verbatim review evidence.

## User Stories

1. As a pipeline maintainer, I want to start with a saved scrape so that I can reproduce and verify a run.
2. As a pipeline maintainer, I want the loader to accept the completed scraper's payload so that ingestion can proceed without reshaping data by hand.
3. As a pipeline maintainer, I want to retain the recipe metadata that the scraper supplies so that the final output preserves the source context.
4. As a recipe reader, I want the source ingredient wording to survive normalization so that details like “packed” and “softened” remain available.
5. As a pipeline maintainer, I want ingredients and source steps to have IDs so that edits can target the correct occurrence.
6. As a recipe reader, I want a source step to retain its wording and placement so that other actions within it survive a targeted change.
7. As a pipeline maintainer, I want exact normalized quantities where the text supports them so that calculations can be checked.
8. As a pipeline maintainer, I want the source review text and its available metadata to survive normalization so that evidence can be checked.
9. As a recipe reader, I want eligible reviews from both sources ranked by helpful-vote count so that the review with the most votes is evaluated first.
10. As a recipe reader, I want the pipeline to try the next eligible review after a skip so that a lower-ranked actionable suggestion can still improve the recipe.
11. As a recipe reader, I want a highly voted review that only praises the recipe to be skipped so that popularity alone cannot produce a change.
12. As a recipe reader, I want the model to recognize a plausible improvement in a vague review so that the reviewer can describe it in their own words.
13. As a recipe reader, I want reported results and inferred benefits labeled clearly so that I can tell where each explanation comes from.
14. As a recipe reader, I want every meaningful, actionable change from the chosen review considered so that useful independent improvements are captured.
15. As a recipe reader, I want exact changed amounts, times, and temperatures so that I can reliably follow the recipe.
16. As a recipe reader, I want clear physical cues such as “until firm” available so that a technique change can describe what I should observe.
17. As a recipe reader, I want a proposal to identify white sugar or brown sugar precisely so that similarly worded ingredients stay distinct.
18. As a recipe reader, I want changes to add, replace, or remove ingredient lines and steps so that the recipe can reflect the suggestion.
19. As a recipe reader, I want insertions before the first or after the last line or step so that prep and finishing techniques go in the right place.
20. As a recipe reader, I want an ingredient removal and its necessary instruction update applied together so that the resulting recipe is usable.
21. As a pipeline maintainer, I want invalid targets, unverified quantities, and unsupported evidence reported so that I can investigate them.
22. As a recipe reader, I want independently valid modifications to survive another modification's rejection so that one error does not discard all improvements.
23. As a pipeline maintainer, I want conflicts resolved consistently and logged so that I can reproduce the selected result.
24. As a recipe reader, I want the enhanced recipe to show actual changes so that I can compare the original and enhanced versions.
25. As a recipe reader, I want each change tied to the exact words of a specific review so that I can inspect the basis for it.
26. As a recipe reader, I want an unchanged recipe and a reason when nothing applies so that I can still use the completed result.
27. As a pipeline maintainer, I want unexpected application failures reported with the failed operation so that I can diagnose them without losing source data.
28. As a pipeline maintainer, I want to verify each stage as it lands so that faults are visible before the entire pipeline is built.
29. As a prompt owner, I want the Stage 3 system prompt and examples captured for review so that the model's instructions reflect the agreed rules.
30. As a pipeline maintainer, I want a separate development recipe set so that I can improve the pipeline while keeping the final comparison independent.
31. As an evaluation judge, I want paired baseline and enhanced outputs for the same recipes so that I can compare them directly.
32. As an evaluation judge, I want separate scores for selection, proposal, and application so that I can locate where quality changed.

## Implementation Decisions

### 1. Scrape the recipe and review candidates

The scraper is implemented and owned by the requester. Its input is a source recipe page. It writes a recipe ID, title, ingredient and instruction string arrays, available recipe metadata, one most helpful positive review or null, and an array of up to 10 featured tweaks. Recipe metadata includes prep, cook, and total time, servings, and yield.

Each review carries its text, rating, reviewer name, and helpful-vote count. A date is present when available. The scraper passes featured tweaks in source order and currently omits the upstream review ID and permalink. The handoff preserves review text as received from the scraper for downstream quote matching.

### 2. Load and normalize the saved scrape

Consume the saved scrape and emit normalized recipe JSON with review candidates. Preserve the original text and relative order of ingredient lines and source steps. Give each occurrence a stable ID within the source snapshot. Preserve one editable step per source instruction entry. Parse an ingredient's name, exact quantity, and unit when the line supports it. Leave unavailable structured values unset or null and retain the original text. Preserve source recipe metadata when supplied.

Keep full review text in one field with a local review ID and available review metadata, including helpful-vote count. Keep the most helpful review and featured tweaks distinguishable. Order eligible five-star candidates across both sources by descending helpful-vote count, with known counts ahead of unknown counts. Preserve input order for ties, including when all counts are unknown. When a captured review can be identified as the same review in both sources, include it once.

### 3. Classify one candidate and propose modifications

Evaluate candidates in the ranked order supplied by Stage 2. Pass the normalized recipe and one review per LLM request. Use the approved Stage 3 system rules and all 21 example input and response pairs as compact JSON messages. The LLM returns a review-specific skip with a reason or a proposal containing all distinct, meaningful, actionable modifications. Each modification has an ID, exact review evidence, a benefit labeled reported or inferred, and its grouped edits.

Helpful votes can support the model's judgment. A modification still needs a change described or suggested in the review. The model selects the supporting quote from the full text. Require exact or unambiguously calculable changed quantities, times, and temperatures. Observable cues can make a technique actionable. Skip unspecified changes such as “a little less white sugar,” guesses, and calculations that require an unsupported conversion. Use a structured calculation for relative ingredient quantities so the validator can check the result.

Combine compatible changes for a target. If the review offers incompatible alternatives, propose the better-supported one, with review order breaking a tie. Order independent proposals by support, using review order for ties. Group linked changes, including ingredient changes and explicit instructions that need to change with them.

A semantic skip advances to the next ranked eligible review. Record the skipped review and reason for diagnosis. The Stage 3 result returns the first proposal and its originating review. An empty pool or a pool exhausted by semantic skips yields no proposal. Provider retries use the same review. Report a persistent provider or response failure as an operational failure with the attempted review's identity.

### 4. Route the proposed edits

Consume the normalized recipe and proposal. Resolve the exact target or anchor ID to the ingredient or instruction section. Support replace and remove by target ID. Support insert before or after an existing anchor ID, including the first or last item. Return routed modifications with their grouped edits and report unknown IDs or unresolved anchors with candidate and modification context.

### 5. Validate the routed modifications

Consume the routed modifications and the source snapshot. Verify operation requirements, target and anchor existence, and that all evidence quotes appear verbatim in the originating review. Validate exact changed values and calculations, reject negative ingredient quantities, and require linked instruction edits when a removal or substitution would leave a clear reference to an ingredient the recipe no longer uses. Distinguish clear dangling references from instructions such as “Mix the dry ingredients.”

Accept a modification as a unit. If multiple valid modifications still conflict, keep the first valid one in proposal order and log the kept and rejected IDs and the affected target. Reject invalid groups with console diagnostics that identify the review, modification, target where available, and reason. Pass the accepted plan and its verified evidence forward. If a review produces no valid modifications, advance to the next eligible review. When the pool is exhausted, pass forward an empty plan for an unchanged recipe.

### 6. Apply the validated plan

Apply only validated edits to a working copy of the source recipe. Preserve unrelated content and apply insertions in a deterministic order. Emit the complete resulting recipe and actual change records with modification IDs, operations, targets, and before and after text where applicable. An unexpected application failure fails the run, preserves the source recipe, and logs the failed operation.

### 7. Generate the final recipe and evidence trail

Generate the final JSON from actual applied changes. Include the complete recipe, outcome, and a per-modification trail with actual changes, the reported or inferred benefit, and verified review evidence tied to its source review. If candidate processing completes with no applied change, return the original recipe with an unchanged outcome and a reason. Surface an unexpected run failure as a failure outcome.

## Testing Decisions

Verify each stage as it lands at its public input and output boundary. Use saved inputs and inspect observable outputs and diagnostics. Use the existing saved-recipe and pipeline entry points as prior art for fixtures and running a single recipe. Stub the model provider for deterministic Stage 3 contract and orchestration checks. Use real model runs to evaluate judgment and prompt behavior.

| Stage | Verify as the stage lands |
| --- | --- |
| 1 | Save a real scrape and confirm its recipe fields, flat ingredients and instructions, and primary and featured review shape. Cover a missing primary and an empty list with saved inputs. |
| 2 | Check stable IDs, original text, exact parsed fractions, recipe metadata, and eligible candidates ranked by helpful-vote count across both sources. Cover ties and missing counts. |
| 3 | Check ranked progression after semantic skips, the first proposal, an exhausted candidate pool, and distinct operational failures. Check grouped proposals, supported calculations, evidence, and reported versus inferred benefits. |
| 4 | Check exact routing for both sections. Verify replace, remove, and inserts before and after anchors. Verify that similar ingredient names and unknown IDs produce the right outcome. |
| 5 | Check exact quote verification, invalid amounts and conversions, dangling ingredient references, group atomicity, first-valid conflict resolution, and loud diagnostics with independently valid groups retained. |
| 6 | Check the working copy, actual change records, and ordering. Force an application failure to confirm the source remains intact and the operation is identified. |
| 7 | Check enhanced and unchanged results, the full recipe, the evidence trail, and the distinction between a completed unchanged run and a run failure. |

### 15 development recipes

Build a set of 15 development recipes under `data/training_data/`. Start with the six existing recipe IDs and add nine distinct recipes. Use current Stage 1 JSON for each recipe and verify that the set has no IDs in common with the held-out inputs. Use the set to find gaps in classification, proposals, routing, and validation, and to improve the prompt and stage behavior. Record the review, expected behavior, observed result, and the point of failure so that improvements can be checked again on the same input.

### 10 held-out recipes

A separate agent will collect 10 new recipes and capture the baseline before the Stage 2–7 replacement. Use the current Stage 1-compatible runner with the exact saved scrape payloads. Capture the version and model settings, selected review, proposal, and final output or failure. Freeze the input snapshots and preserve run artifacts for judging. After Stages 2–7 are complete, rerun the same 10 payloads and present paired results. Keep these recipes out of prompt tuning. Record runtime, model calls, and input and output tokens when available for the performance comparison.

The requester judges both runs using three Y/N checks.

| Check | Mark Y when |
| --- | --- |
| Is the chosen review correct? | The chosen review is first in helpful-vote order among eligible reviews that support a meaningful, applicable modification. An unchanged result also earns Y when no eligible review qualifies. |
| Is the proposed edit correct? | The proposal captures the supported changes from the chosen review and gets the targets and values right. |
| Was the proposed edit applied successfully? | The recipe reflects the accepted edits and preserves unrelated content. |

Score the last two checks independently. An incorrect proposal can still have been applied as proposed. For a correctly unchanged result, leave both edit checks blank and exclude those blanks from their denominators. Compare paired cases and report Y counts with their scored denominators.

For a Stage 3 diagnostic, an independent judge can score review selection and proposal correctness from the saved inputs and outputs. Use the Stage 2 ranking and check every higher-ranked eligible review for a meaningful, actionable modification. Record the selected review's rank, any earlier qualifying review, and the rationale for both scores. The application check belongs to the apply stage.

## Out of Scope

- A redesign of the completed scraper or broader acquisition of ordinary reviews.
- Model fine-tuning or using held-out reviews as prompt examples.
- A second LLM generation step for presentation.
- Approximate target matching or speculative changes based on guessed quantities.

## Further Notes

The [approved Stage 3 prompt](./stage-3-system-prompt.md) measures 5,657 fixed input tokens for the system rules and 21 compact examples with canonical IDs, measured with the baseline tokenizer before the recipe, candidate review, and message overhead.

The saved baseline used the Stage 1-compatible loader. It followed source order for featured tweaks and used its text heuristic to screen reviews. Record the selected review for each run so the comparison shows the effect of the selection policy.

The first saved Stage 3 held-out run used primary-first selection with fallback. A later rerun ranked candidates by helpful votes and evaluated one review per recipe. The current rule keeps that ranking and advances after semantic skips.
