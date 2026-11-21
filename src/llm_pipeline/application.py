"""Apply a validated Stage 5 plan to the Stage 2 recipe snapshot."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .normalization import _ingredient


@dataclass
class _SourceSlot:
    index: int
    source: dict
    current: dict | None
    before: list[dict] = field(default_factory=list)
    after: list[dict] = field(default_factory=list)


def apply_validated_edits(recipe: dict[str, Any], stage5_result: dict[str, Any]) -> dict[str, Any]:
    """Return detached recipe and change records, or a failure without partial output."""
    status = stage5_result.get("status")
    review_id = stage5_result.get("review_id")
    result = {
        "status": "failed", "recipe": None, "recipe_id": recipe.get("recipe_id"),
        "review_id": review_id, "selected_review": deepcopy(stage5_result.get("selected_review")),
        "next_review": deepcopy(stage5_result.get("next_review")),
        "modifications": [], "applied_changes": [],
        "diagnostics": deepcopy(stage5_result.get("diagnostics", [])),
    }
    if status == "failed":
        return result

    context = {"review_id": review_id, "modification_id": None, "section": None,
               "operation": None, "target": None}
    try:
        expected_id = stage5_result.get("recipe_id")
        if expected_id is not None and expected_id != recipe.get("recipe_id"):
            raise ValueError(f"Stage 5 recipe ID {expected_id!r} does not match the source recipe ID")
        if status == "continue":
            return {**result, "status": "continue"}
        if status not in ("validated", "empty"):
            raise ValueError(f"unsupported Stage 5 status {status!r}")

        working = deepcopy(recipe)
        modifications = stage5_result["modifications"]
        if not isinstance(modifications, list) or (status == "empty" and modifications):
            raise ValueError("invalid Stage 5 modification list")
        if not modifications:
            return {**result, "status": "unchanged", "recipe": working}

        slots = {
            section: {row["id"]: _SourceSlot(index, row, row)
                      for index, row in enumerate(working[section])}
            for section in ("ingredients", "instructions")
        }
        next_ids = {
            section: max((int(row_id.rsplit("-", 1)[1]) for row_id in entries), default=0) + 1
            for section, entries in slots.items()
        }
        groups, changes = [], []
        for modification in modifications:
            context.update(modification_id=None, section=None, operation=None, target=None)
            mid = modification["id"]
            context["modification_id"] = mid
            count_before = len(changes)
            for edit in modification["edits"]:
                context.update(section=None, operation=None, target=None)
                context.update(section=edit.get("section"), operation=edit.get("operation"),
                               target=edit.get("anchor_id") or edit.get("target_id"))
                change = _apply_edit(slots, next_ids, edit)
                if change is not None:
                    changes.append({"modification_id": mid, **change})
            if len(changes) > count_before:
                groups.append({
                    "id": mid, "review_id": review_id,
                    "evidence_quotes": deepcopy(modification["evidence_quotes"]),
                    "benefit": deepcopy(modification.get("benefit")),
                    "applied_changes": changes[count_before:],
                })

        for section, entries in slots.items():
            # Keep a source slot for insertions even when its original row was removed.
            working[section] = [
                row for slot in entries.values()
                for row in [*slot.before, slot.current, *slot.after] if row is not None
            ]
    except Exception as exc:
        result["diagnostics"].append({**context, "reason": f"{type(exc).__name__}: {exc}"})
        return result

    return {**result, "status": "applied" if changes else "unchanged", "recipe": working,
            "modifications": groups, "applied_changes": changes}


def _apply_edit(slots: dict, next_ids: dict, edit: dict) -> dict | None:
    section, operation = edit["section"], edit["operation"]
    ref = edit["anchor_id"] if operation == "insert" else edit["target_id"]
    slot = slots[section].get(ref)
    matched = edit.get("matched_record")
    if (slot is None or not isinstance(matched, dict) or matched.get("id") != ref
            or matched.get("text") != slot.source["text"] or edit.get("index") != slot.index):
        raise ValueError(f"resolved reference {ref!r} does not match the source snapshot")

    change = {"section": section, "operation": operation, "target_id": ref}
    if operation == "insert":
        position, text = edit["position"], edit["text"]
        if position not in ("before", "after") or not isinstance(text, str) or not text.strip():
            raise ValueError("insert requires a valid position and non-empty text")
        index = next_ids[section]
        row = (_ingredient(text, index) if section == "ingredients"
               else {"id": f"instruction-{index:04d}", "text": text})
        (slot.before if position == "before" else slot.after).append(row)
        next_ids[section] += 1
        return {**change, "target_id": row["id"], "anchor_id": ref,
                "position": position, "after": text}

    current = slot.current
    if current is None:
        raise ValueError(f"target {ref!r} has already been removed")
    change["before"] = current["text"]
    if operation == "remove":
        slot.current = None
        return change
    if operation != "replace":
        raise ValueError(f"unsupported operation {operation!r}")
    text = edit["replacement_text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("replace requires non-empty text")
    if text == current["text"]:
        return None
    fields = _ingredient(text, 1) if section == "ingredients" else {"text": text}
    slot.current = {**current, **fields, "id": ref}
    return {**change, "after": text}
