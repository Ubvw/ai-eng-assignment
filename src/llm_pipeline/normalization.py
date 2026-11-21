"""Normalize a saved scraper payload at the Stage 2 boundary."""

import re
from fractions import Fraction
from typing import Any, Dict, Optional


_AMOUNT = re.compile(r"^(?P<amount>\d+(?:\.\d+)?(?:\s+(?:\d+/\d+|[¼½¾⅓⅔⅛⅜⅝⅞])|/\d+)?|\d+/\d+|[¼½¾⅓⅔⅛⅜⅝⅞])\s*(?P<rest>.*)$")
_UNITS = {
    "tsp": "teaspoon", "teaspoons": "teaspoon", "teaspoon": "teaspoon",
    "tbsp": "tablespoon", "tablespoons": "tablespoon", "tablespoon": "tablespoon",
    "c": "cup", "cups": "cup", "cup": "cup", "oz": "ounce", "ounces": "ounce",
    "lb": "pound", "lbs": "pound", "pounds": "pound", "g": "gram", "gram": "gram",
    "kg": "kilogram", "ml": "milliliter", "l": "liter", "pinch": "pinch",
}
_UNICODE_FRACTIONS = {"¼": Fraction(1, 4), "½": Fraction(1, 2), "¾": Fraction(3, 4),
                      "⅓": Fraction(1, 3), "⅔": Fraction(2, 3), "⅛": Fraction(1, 8),
                      "⅜": Fraction(3, 8), "⅝": Fraction(5, 8), "⅞": Fraction(7, 8)}


def _quantity(raw: str) -> Optional[str]:
    try:
        bits = raw.split()
        if len(bits) == 2 and ("/" in bits[1] or bits[1] in _UNICODE_FRACTIONS):
            value = Fraction(bits[0]) + (_UNICODE_FRACTIONS[bits[1]] if bits[1] in _UNICODE_FRACTIONS else Fraction(bits[1]))
        elif raw in _UNICODE_FRACTIONS:
            value = _UNICODE_FRACTIONS[raw]
        else:
            value = Fraction(raw)
        return str(value)
    except (ValueError, ZeroDivisionError):
        return None


def _ingredient(text: str, index: int) -> Dict[str, Any]:
    parsed = _AMOUNT.match(text.strip())
    quantity = None
    unit = None
    name = text.strip()
    if parsed:
        quantity = _quantity(parsed.group("amount"))
        rest = parsed.group("rest").strip()
        unit_match = re.match(r"([^\s,]+)(?:\s+|$)(.*)", rest)
        unit_token = unit_match.group(1).lower().rstrip(".,") if unit_match else ""
        if unit_token.startswith("-"):
            unit_token = unit_token[1:]
        if unit_match and unit_token in _UNITS:
            unit = _UNITS[unit_token]
            rest = unit_match.group(2)
        name = rest.strip() or text.strip()
    return {"id": f"ingredient-{index:04d}", "text": text, "name": name,
            "quantity": quantity, "unit": unit}


def normalize_recipe_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return addressable recipe rows and five-star candidates ranked by helpful votes."""
    ingredients = data.get("ingredients") if isinstance(data.get("ingredients"), list) else []
    instructions = data.get("instructions") if isinstance(data.get("instructions"), list) else []
    recipe = {key: value for key, value in data.items()
              if key not in {"ingredients", "instructions", "reviews", "featured_tweaks",
                             "most_helpful_positive_review"}}
    recipe["ingredients"] = [_ingredient(str(text), i + 1) for i, text in enumerate(ingredients)]
    recipe["instructions"] = [{"id": f"instruction-{i + 1:04d}", "text": str(text)}
                               for i, text in enumerate(instructions)]

    pool = []
    primary = data.get("most_helpful_positive_review")
    if isinstance(primary, dict):
        pool.append(("primary", 0, primary))
    featured = data.get("featured_tweaks") or []
    if isinstance(featured, dict):
        featured = [featured]
    if isinstance(featured, list):
        pool.extend(("featured", i, r) for i, r in enumerate(featured) if isinstance(r, dict))
    # Legacy payloads remain readable if the scraper-specific fields are absent.
    if not pool and isinstance(data.get("reviews"), list):
        pool.extend(("legacy", i, r) for i, r in enumerate(data["reviews"]) if isinstance(r, dict))

    candidates = []
    seen = {}
    for kind, index, raw in pool:
        if not isinstance(raw.get("text"), str) or not raw["text"].strip():
            continue
        rating = raw.get("rating")
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            continue
        if rating != 5:
            continue
        reviewer = raw.get("reviewer", raw.get("username", raw.get("reviewer_name")))
        votes = next((raw[k] for k in ("helpful_votes", "helpful_vote_count", "helpful_count", "helpfulCount", "vote_count")
                      if raw.get(k) is not None), None)
        try:
            votes = int(votes) if votes is not None else None
        except (TypeError, ValueError):
            votes = None
        # Deduplicate only when the text and an available reviewer identity agree.
        identity = (raw["text"], reviewer) if reviewer else None
        if identity and identity in seen:
            kept_votes = seen[identity]["helpful_votes"]
            if votes is not None and (kept_votes is None or votes > kept_votes):
                seen[identity]["helpful_votes"] = votes
            continue
        candidate = {
            "id": f"review-{kind}-{index + 1:04d}", "source": kind, "text": raw["text"],
            "rating": rating, "reviewer": reviewer, "helpful_votes": votes,
            "date": raw.get("date"), "permalink": raw.get("permalink"),
            "metadata": {
                key: value for key, value in raw.items()
                if key not in {"text", "rating", "reviewer", "username", "reviewer_name",
                               "helpful_votes", "helpful_vote_count", "helpful_count",
                               "helpfulCount", "vote_count", "date", "permalink"}
            },
        }
        candidates.append(candidate)
        if identity:
            seen[identity] = candidate
    # Stable sorting keeps the original primary/source order when vote counts tie.
    candidates.sort(key=lambda row: (row["helpful_votes"] is None, -(row["helpful_votes"] or 0)))
    return {"recipe": recipe, "review_candidates": candidates}
