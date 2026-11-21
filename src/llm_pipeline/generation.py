"""Assemble Stage 7 results from the changes that Stage 6 actually applied."""

from copy import deepcopy
from typing import Any


def generate_final_recipe(stage6_result: dict[str, Any]) -> dict[str, Any]:
    """Return a detached result with review evidence for each applied modification."""
    result = {
        "status": "failed", "recipe": None, "recipe_id": None, "review_id": None,
        "selected_review": None, "modifications": [], "diagnostics": [],
    }
    modification_id = None
    try:
        if not isinstance(stage6_result, dict):
            raise ValueError("Stage 6 result must be an object")
        for key in ("recipe_id", "review_id", "selected_review"):
            result[key] = deepcopy(stage6_result.get(key))
        diagnostics = stage6_result.get("diagnostics", [])
        if not isinstance(diagnostics, list) or any(not isinstance(item, dict) for item in diagnostics):
            raise ValueError("Stage 6 diagnostics must be a list of objects")
        result["diagnostics"] = deepcopy(diagnostics)

        status = stage6_result.get("status")
        if status == "failed":
            return {**result, "reason": "Stage 6 failed."}
        if status == "continue":
            return {**result, "status": "continue", "next_review": deepcopy(stage6_result["next_review"])}
        if status not in ("applied", "unchanged"):
            raise ValueError(f"unsupported Stage 6 status {status!r}")

        recipe = stage6_result["recipe"]
        if not isinstance(recipe, dict) or not all(
            isinstance(recipe.get(section), list) for section in ("ingredients", "instructions")
        ):
            raise ValueError("Stage 6 result must include the complete recipe")
        if status == "unchanged":
            return {**result, "status": "unchanged", "recipe": deepcopy(recipe),
                    "selected_review": None, "reason": "No applicable edits were applied."}

        groups = stage6_result["modifications"]
        if not isinstance(groups, list) or any(not isinstance(group, dict) for group in groups):
            raise ValueError("Stage 6 modifications must be a list of objects")
        selected_review = result["selected_review"]
        review_id = result["review_id"]
        if (not isinstance(review_id, str) or not review_id or not isinstance(selected_review, dict)
                or selected_review.get("id") != review_id or not isinstance(selected_review.get("text"), str)):
            raise ValueError("Stage 6 applied result must identify its selected review")

        modifications = []
        for group in groups:
            modification_id = group.get("id")
            changes = group["applied_changes"]
            if not isinstance(changes, list) or any(not isinstance(change, dict) for change in changes):
                raise ValueError("applied changes must be a list of objects")
            if not changes:
                continue
            if not isinstance(modification_id, str) or not modification_id:
                raise ValueError("applied modification must have a non-empty ID")
            quotes = group["evidence_quotes"]
            if (group.get("review_id") != review_id or not isinstance(quotes, list) or not quotes
                    or any(not isinstance(q, str) or not q or q not in selected_review["text"] for q in quotes)):
                raise ValueError("modification must have verbatim evidence from the selected review")
            benefit = group.get("benefit")
            if (not isinstance(benefit, dict) or benefit.get("basis") not in ("reported", "inferred")
                    or not isinstance(benefit.get("description"), str) or not benefit["description"]):
                raise ValueError("modification must have a reported or inferred benefit")
            modifications.append({
                "id": modification_id, "changes": deepcopy(changes), "benefit": deepcopy(benefit),
                "evidence": [{"review_id": review_id, "quote": quote} for quote in quotes],
            })
        if not modifications:
            raise ValueError("Stage 6 reported an applied recipe without any applied changes")
    except (KeyError, ValueError) as exc:
        result["diagnostics"].append({
            "review_id": result["review_id"], "modification_id": modification_id,
            "reason": f"{type(exc).__name__}: {exc}",
        })
        return {**result, "reason": "Stage 7 could not generate the final recipe."}

    return {**result, "status": "enhanced", "recipe": deepcopy(recipe), "modifications": modifications}
