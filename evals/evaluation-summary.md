# Held-out evaluation summary

**Run date:** 2026-11-22  
**Scope:** 10 held-out saved scrapes in `evals/test_data/`, compared with the paired outputs in `evals/baseline/`.  
**Rubric:** The three Y/N checks in [spec.md](../.scratch/recipe-enhancement-pipeline/spec.md#10-held-out-recipes), with the application/preservation check split into edit application and recipe completeness for diagnosis.

## Aggregate scores

| Check | Baseline | New pipeline |
| --- | ---: | ---: |
| Correct review selection | 5/10 | 9/10 |
| Correct proposed edits | 2/10 | 6/10 |
| Accepted ingredient/instruction edits applied correctly | 10/10 | 10/10 |
| Is the recipe complete? | 0/10 | 10/10 |


## Metric definitions

- **Correct review selection** — Eligible reviews are five-star reviews. Score Y when the selected review is the first in helpful-vote order among eligible reviews that supports a meaningful, applicable change. Y also applies when no eligible review qualifies and the result is unchanged.
- **Correct proposed edits** — Y when the proposal captures the supported changes from the selected review and identifies the right targets and values.
- **Accepted edits applied correctly** — Y when the validated ingredient and instruction edits appear in the final recipe, while unrelated recipe lines remain intact and in order.
- **Is the recipe complete?** — Y when the final output includes the complete ingredient and instruction lists and preserves the source recipe ID (or an equivalent original ID), title, and supplied prep time, cook time, total time, servings, and yield values. All source fields must be present and match. This metric separates completeness from edit application.

## Per-recipe scores

Scores are listed as **selection / proposal / edit application / recipe complete**.

| Recipe | Baseline | New pipeline |
| --- | --- | --- |
| 13974 — Peanut Noodles | N / N / Y / N | Y / N / Y / Y |
| 15641 — Grilled Chicken with Herbs | N / N / Y / N | N / N / Y / Y |
| 221062 — Chicken Broccoli Salad | Y / Y / Y / N | Y / Y / Y / Y |
| 22158 — Pasta Lasagna | Y / N / Y / N | Y / Y / Y / Y |
| 229445 — Israeli Couscous and Cheese | Y / N / Y / N | Y / Y / Y / Y |
| 24380 — Green Salad with Cranberry Vinaigrette | Y / N / Y / N | Y / N / Y / Y |
| 255272 — Spanish Rice Stuffed Bell Peppers | N / N / Y / N | Y / N / Y / Y |
| 8091 — Ho Ho Cake | N / N / Y / N | Y / Y / Y / Y |
| 9138 — Green Beans with Walnuts | Y / N / Y / N | Y / Y / Y / Y |
| 9397 — Green Bell Pepper Jelly | N / Y / Y / N | Y / Y / Y / Y |

## Reading the results

- The new pipeline's selection miss was recipe 15641. It chose a review suggesting a side pairing and vague herb reductions; the judge treated those as non-actionable recipe changes. The next-ranked review had an actionable preparation change. If side pairings count as recipe modifications, new selection becomes 10/10 and proposal becomes 7/10.
- The baseline selected an ineligible four-star review for recipes 13974, 15641, and 8091.
- Both runs applied their recorded ingredient/instruction changes on all ten recipes. The baseline completeness score is 0/10: its titles were changed, all supplied `total_time` values became null, all `yield` values were omitted, and prep/cook times differed in 8/10 and 7/10 outputs. It did preserve servings on all ten recipes and the original ID as `original_recipe_id`. The new output preserved all compared source metadata fields on all ten recipes.
- Baseline artifacts contain applied changes and reasoning, but not raw Stage 3 proposals or insertion anchors. Baseline proposal scores are therefore inferred from the recorded changes; anchor fidelity cannot be checked.

## Artifacts

- New per-recipe outputs and per-review Stage 3–5 traces: `evals/runs/test_data/recipe_<id>_result.json`
- Frozen held-out inputs: `evals/test_data/recipe_<id>.json`
- Baseline outputs: `evals/baseline/enhanced_<id>_<slug>.json`
