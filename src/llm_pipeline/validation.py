"""Validate exact-ID Stage 4 groups against the Stage 2 source snapshot."""

import re
from fractions import Fraction
from typing import Any

from .normalization import _ingredient, normalize_recipe_data


def validate_modifications(raw_recipe: dict[str, Any], stage4_result: dict[str, Any]) -> dict[str, Any]:
    """Return an independently validated plan; never mutate either input."""
    normalized = normalize_recipe_data(raw_recipe)
    recipe, candidates = normalized["recipe"], normalized["review_candidates"]
    review_id = stage4_result.get("review_id")
    review = next((candidate for candidate in candidates if candidate["id"] == review_id), None)
    status = stage4_result.get("status")
    diagnostics = list(stage4_result.get("diagnostics", [])) if isinstance(stage4_result.get("diagnostics", []), list) else []
    if status in ("failed", "error"):
        return _result("failed", review_id, [], diagnostics, None, "Stage 4 reported failure")
    if stage4_result.get("modifications") and review is None:
        return _result("failed", review_id, [], diagnostics, None, "originating review is not an eligible Stage 2 candidate")
    if not isinstance(stage4_result.get("modifications", []), list):
        return _result("failed", review_id, [], diagnostics, None, "modifications must be a list")

    rows = {section: {row["id"]: row for row in recipe[section]} for section in ("ingredients", "instructions")}
    accepted, occupied = [], {}
    for mod in stage4_result.get("modifications", []):
        mid = mod.get("id") if isinstance(mod, dict) else None
        reason, target = _validate_group(mod, review, rows, recipe)
        if reason is None:
            touched = [_touch(edit) for edit in mod["edits"]]
            conflict = next(((key, occupied[key]) for key in touched if key in occupied), None)
            if conflict:
                key, kept = conflict
                reason = f"conflicts with kept modification {kept!r} on target {key[1]!r}"
                diagnostics.append(_diagnostic(review_id, mid, target or key[1], reason, kept_modification_id=kept))
        if reason:
            if not any(d.get("modification_id") == mid and d.get("reason") == reason for d in diagnostics):
                diagnostics.append(_diagnostic(review_id, mid, target, reason))
            continue
        accepted.append(mod)
        for key in touched:
            occupied[key] = mid

    next_review = None
    outcome = "validated" if accepted else "empty"
    if not accepted and review is not None:
        candidate_ids = [item["id"] for item in candidates]
        next_review = next((item for item in candidates[candidate_ids.index(review_id) + 1:] if item["id"] != review_id), None)
        if next_review:
            outcome = "continue"
    elif not accepted and status not in ("exhausted", "empty", None) and stage4_result.get("modifications"):
        outcome = "empty"
    # Routing diagnostics can include no modification_id; keep them visible as prior-stage evidence.
    return {"status": outcome, "review_id": review_id, "selected_review": review,
            "modifications": accepted, "diagnostics": diagnostics,
            "next_review": next_review, "recipe_id": recipe.get("recipe_id")}


def _validate_group(mod: Any, review: dict | None, rows: dict, recipe: dict) -> tuple[str | None, str | None]:
    if not isinstance(mod, dict) or not isinstance(mod.get("id"), str) or not mod["id"]:
        return "modification must have a non-empty ID", None
    edits = mod.get("edits")
    if not isinstance(edits, list) or not edits:
        return "edits must be a non-empty list", None
    if review is None:
        return "originating review was not found", None
    quotes = mod.get("evidence_quotes")
    if not isinstance(quotes, list) or not quotes or any(not isinstance(q, str) or not q or q not in review["text"] for q in quotes):
        return "evidence quote is missing or not verbatim in originating review", None
    resolved = []
    evidence = " ".join(quotes)
    for edit in edits:
        if not isinstance(edit, dict):
            return "edit must be an object", None
        op, section = edit.get("operation"), edit.get("section")
        if section not in rows:
            return "routed edit has no valid section", None
        if op in ("replace", "remove"):
            ref = edit.get("target_id")
            text = edit.get("replacement_text")
            if op == "replace" and (not isinstance(text, str) or not text.strip()):
                return "replace requires non-empty replacement_text", ref
        elif op == "insert":
            ref, text = edit.get("anchor_id"), edit.get("text")
            if edit.get("position") not in ("before", "after"):
                return "insert position must be before or after", ref
            if not isinstance(text, str) or not text.strip():
                return "insert requires non-empty text", ref
        else:
            return f"unsupported operation {op!r}", edit.get("target_id")
        if not isinstance(ref, str) or ref not in rows[section]:
            return f"unknown {('anchor' if op == 'insert' else 'target')} ID {ref!r} in {section}", ref
        actual = rows[section][ref]
        matched = edit.get("matched_record")
        if not isinstance(matched, dict) or matched.get("id") != ref or matched.get("text") != actual.get("text"):
            return f"routed reference {ref!r} does not match source snapshot", ref
        if edit.get("index") != recipe[section].index(actual):
            return f"routed index for {ref!r} does not match source snapshot", ref
        if op == "replace" and section == "ingredients":
            reason = _quantity_valid(actual, text, edit.get("quantity_change"))
            if reason:
                return reason, ref
        if op == "insert" and section == "ingredients" and re.match(r"^\s*-\s*\d", text):
            return "ingredient quantity cannot be negative", ref
        if op in ("replace", "insert") and section == "instructions":
            old_numbers = _numbers(actual.get("text", "")) if op == "replace" else set()
            for value in _numbers(text):
                if value not in old_numbers and value not in _numbers(evidence):
                    return f"changed instruction value {value!r} is not supported by exact review evidence", ref
        resolved.append((edit, ref, actual))

    # Validate the final ingredient references after all edits in this group.
    removed_names = set()
    for edit, ref, row in resolved:
        if edit["operation"] in ("remove", "replace") and edit["section"] == "ingredients":
            replacement = edit.get("replacement_text")
            changed = _ingredient(replacement, 1)["name"] if replacement else None
            old_name = row.get("name") or row["text"]
            if changed is None or changed.casefold() != old_name.casefold():
                removed_names.add(old_name)
    changed_ingredient_ids = {ref for edit, ref, _ in resolved
                              if edit["section"] == "ingredients" and edit["operation"] in ("remove", "replace")}
    remaining_names = {row.get("name", "").casefold() for row in recipe["ingredients"]
                       if row["id"] not in changed_ingredient_ids}
    for edit, _, row in resolved:
        if edit["section"] == "ingredients" and edit["operation"] in ("remove", "replace"):
            replacement = edit.get("replacement_text")
            if replacement:
                remaining_names.add(_ingredient(replacement, 1)["name"].casefold())
    removed_names = {name for name in removed_names if name.casefold() not in remaining_names}
    if removed_names:
        instructions = list(recipe["instructions"])
        for edit, ref, _ in resolved:
            if edit["section"] == "instructions" and edit["operation"] in ("remove", "replace"):
                idx = edit["index"]
                instructions[idx] = {**instructions[idx], "text": edit.get("replacement_text", "") if edit["operation"] == "replace" else ""}
        for row in instructions:
            if any(_clear_reference(name, row["text"]) for name in removed_names):
                return "ingredient change leaves a clear dangling instruction reference; coordinate an instruction edit", row["id"]
    return None, None


def _quantity_valid(old: dict, new_text: str, change: Any) -> str | None:
    if re.match(r"^\s*-\s*\d", new_text):
        return "ingredient quantity cannot be negative"
    new = _ingredient(new_text, 1)
    if new["quantity"] is not None and Fraction(new["quantity"]) < 0:
        return "ingredient quantity cannot be negative"
    old_qty, new_qty = old.get("quantity"), new.get("quantity")
    if change is None:
        if old.get("unit") and new.get("unit") and old.get("unit") != new.get("unit") and (old_qty is not None or new_qty is not None):
            return "ingredient unit conversion requires explicit supported arithmetic"
        if old_qty != new_qty and (old_qty is not None or new_qty is not None):
            return "changed ingredient quantity requires an explicit supported quantity_change"
        return None
    if not isinstance(change, dict) or old_qty is None or new_qty is None:
        return "quantity_change requires parseable source and replacement quantities"
    if old.get("unit") != new.get("unit") or (change.get("mode") in ("add", "subtract") and change.get("unit") != old.get("unit")):
        return "quantity_change uses an unsupported unit conversion"
    try:
        before = Fraction(old_qty)
        mode = change.get("mode")
        expected = before * Fraction(change["factor"]) if mode == "multiply" else before + (1 if mode == "add" else -1) * Fraction(change["amount"])
        if mode not in ("add", "subtract", "multiply") or expected != Fraction(new_qty):
            return "replacement quantity does not match exact quantity_change arithmetic"
        if expected < 0:
            return "quantity_change produces a negative ingredient quantity"
    except (KeyError, ValueError, ZeroDivisionError, TypeError):
        return "quantity_change arithmetic is malformed or unsupported"
    return None


def _clear_reference(name: str, text: str) -> bool:
    # Match the full, normalized ingredient name; generic cooking phrases are not evidence of a dangling link.
    return bool(name and name.casefold() in text.casefold())


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"(?<!\w)-?\d+(?:\.\d+)?(?:/\d+)?", text))


def _touch(edit: dict) -> tuple[str, str]:
    return (edit["section"], edit.get("target_id") or edit.get("anchor_id"))


def _diagnostic(review_id: Any, mid: Any, target: Any, reason: str, **extra: Any) -> dict:
    return {"review_id": review_id, "modification_id": mid, "target": target,
            "reason": reason, **extra}


def _result(status: str, review_id: Any, mods: list, diagnostics: list, next_review: Any, reason: str) -> dict:
    diagnostics.append(_diagnostic(review_id, None, None, reason))
    return {"status": status, "review_id": review_id, "modifications": mods,
            "diagnostics": diagnostics, "next_review": next_review}
