"""Route Stage 3 edits to exact normalized recipe rows (Stage 4)."""

from typing import Any


def route_modifications(recipe: dict[str, Any], stage3_result: dict[str, Any]) -> dict[str, Any]:
    """Return independently routable proposal groups and diagnostics.

    A modification is kept whole: if one edit is malformed or cannot resolve
    uniquely, none of that group's edits are handed to validation.
    """
    rows = {
        section: recipe.get(section, []) if isinstance(recipe.get(section, []), list) else []
        for section in ("ingredients", "instructions")
    }
    by_id: dict[str, list[tuple[str, int, dict[str, Any]]]] = {}
    for section, entries in rows.items():
        for index, entry in enumerate(entries):
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                by_id.setdefault(entry["id"], []).append((section, index, entry))

    routed, diagnostics = [], []
    if stage3_result.get("decision") != "propose":
        return {"status": stage3_result.get("status", stage3_result.get("decision", "empty")),
                "selected_review": stage3_result.get("selected_review"),
                "review_id": stage3_result.get("review_id"),
                "modifications": [], "diagnostics": []}

    selected_review = stage3_result.get("selected_review")
    review_id = stage3_result.get("review_id") or (selected_review or {}).get("id")
    modifications = stage3_result.get("modifications")
    if not isinstance(modifications, list):
        return {"status": "routed", "selected_review": selected_review,
                "review_id": review_id, "modifications": [],
                "diagnostics": [{"review_id": review_id, "modification_id": None,
                                 "reason": "modifications must be a list"}]}

    for modification in modifications:
        mod_id = modification.get("id") if isinstance(modification, dict) else None
        edits = modification.get("edits") if isinstance(modification, dict) else None
        failure = None
        resolved = []
        if not isinstance(edits, list) or not edits:
            failure = "edits must be a non-empty list"
        else:
            for edit in edits:
                if not isinstance(edit, dict):
                    failure = "edit must be an object"
                    break
                operation = edit.get("operation")
                if operation in ("replace", "remove"):
                    row_id = edit.get("target_id")
                    ref_kind = "target"
                elif operation == "insert":
                    row_id = edit.get("anchor_id")
                    ref_kind = "anchor"
                    if edit.get("position") not in ("before", "after"):
                        failure = "insert position must be 'before' or 'after'"
                else:
                    failure = f"unknown or missing operation {operation!r}"
                if failure:
                    break
                if not isinstance(row_id, str) or not row_id:
                    failure = f"{ref_kind} ID must be a non-empty string"
                    break
                matches = by_id.get(row_id, [])
                if not matches:
                    failure = f"unknown {ref_kind} ID {row_id!r}"
                    break
                if len(matches) != 1:
                    failure = f"ambiguous {ref_kind} ID {row_id!r}"
                    break
                section, index, row = matches[0]
                if operation == "replace" and (not isinstance(edit.get("replacement_text"), str) or not edit["replacement_text"].strip()):
                    failure = "replace requires non-empty replacement_text"
                    break
                if operation == "insert" and (not isinstance(edit.get("text"), str) or not edit["text"].strip()):
                    failure = "insert requires non-empty text"
                    break
                resolved.append({**edit, "section": section, "index": index,
                                 "matched_record": row.copy()})

        if failure:
            diagnostics.append({"review_id": review_id, "modification_id": mod_id,
                                "selected_review": selected_review,
                                "reason": failure})
        elif isinstance(modification, dict):
            routed.append({"review_id": review_id, "selected_review": selected_review,
                           **modification, "edits": resolved})
        else:
            diagnostics.append({"review_id": review_id, "modification_id": None,
                                "selected_review": selected_review,
                                "reason": "modification must be an object"})

    return {"status": "routed", "selected_review": selected_review,
            "review_id": review_id, "modifications": routed,
            "diagnostics": diagnostics}
