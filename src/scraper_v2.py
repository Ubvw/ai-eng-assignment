import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry


def _review_from_model_item(item: Any) -> Optional[Dict]:
    """Keep only the review fields needed by the recipe enhancement pipeline."""
    if not isinstance(item, dict) or not isinstance(item.get("review"), str):
        return None

    text = BeautifulSoup(item["review"], "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s*&\[[^\]]*\]\s*$", "", text)
    if not text:
        return None

    review = {
        "text": text,
        "rating": item.get("starRating"),
        "username": item.get("displayName"),
        "helpful_count": item.get("helpfulCount", 0),
    }
    created = item.get("created")
    if isinstance(created, (int, float)):
        try:
            review["date"] = datetime.fromtimestamp(
                created / 1000, timezone.utc
            ).strftime("%m/%d/%Y")
        except (OverflowError, OSError, ValueError):
            pass

    return review


def _parse_yield(recipe_yield: Any) -> tuple[Optional[str], Optional[str]]:
    if isinstance(recipe_yield, list):
        recipe_yield = recipe_yield[0] if recipe_yield else None
    yield_text = str(recipe_yield).strip() if recipe_yield is not None else None
    servings = re.search(r"\d+(?:\.\d+)?", yield_text or "")
    return yield_text, servings.group(0) if servings else None


def extract_feedback_from_model(payload: Any) -> Dict[str, Any]:
    """Extract the highlighted review and featured tweaks from Allrecipes' model."""
    empty = {"most_helpful_positive_review": None, "featured_tweaks": []}
    if not isinstance(payload, dict):
        return empty

    def feedback_from_aggregated(value: Any) -> Optional[Dict[str, Any]]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return None
        if isinstance(value, dict):
            if "mostHelpful" not in value and "tweaks" not in value:
                return None
            most_helpful = value.get("mostHelpful")
            positive = (
                most_helpful.get("positive")
                if isinstance(most_helpful, dict)
                else None
            )
            tweaks = value.get("tweaks")
            if not isinstance(tweaks, list):
                tweaks = []
            return {
                "most_helpful_positive_review": _review_from_model_item(positive),
                "featured_tweaks": [
                    review
                    for item in tweaks[:10]
                    if (review := _review_from_model_item(item)) is not None
                ],
            }
        return None

    direct = feedback_from_aggregated(payload.get("aggregatedFeedbacks", payload))
    if direct:
        return direct

    # The model response wraps the Vue configuration in ugc_*.inlineScripts.
    for component in payload.values():
        if not isinstance(component, dict):
            continue
        scripts = component.get("inlineScripts", [])
        if not isinstance(scripts, list):
            continue
        for script in scripts:
            content = script.get("content", "") if isinstance(script, dict) else ""
            if not isinstance(content, str):
                continue
            for match in re.finditer(r"\bprops\s*=\s*", content):
                try:
                    props, _ = json.JSONDecoder().raw_decode(content, match.end())
                except json.JSONDecodeError:
                    continue
                if isinstance(props, dict):
                    feedback = feedback_from_aggregated(
                        props.get("aggregatedFeedbacks")
                    )
                    if feedback:
                        return feedback
    return empty


def _request_reviews_model(session, url: str, soup, headers: Dict) -> Optional[Dict]:
    """Request the deferred reviews component using Allrecipes' Globe form."""
    form_data = [
        ("globeDeferVersion", "2"),
        ("cr", "ugc_1"),
    ]

    csrf_input = soup.find(attrs={"name": "CSRFToken"})
    csrf_token = (
        csrf_input.get("value")
        if csrf_input
        else next(
            (cookie.value for cookie in session.cookies if cookie.name == "CSRFToken"),
            None,
        )
    )
    if csrf_token:
        form_data.append(("CSRFToken", csrf_token))

    origin = urlparse(url)
    post_headers = {
        **headers,
        "Origin": f"{origin.scheme}://{origin.netloc}",
        "Referer": url,
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        response = session.post(
            url, data=form_data, headers=post_headers, timeout=(5, 20)
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        print(f"Review request failed; keeping recipe details: {exc}")
        return None
    except ValueError as exc:
        print(f"Review response was not valid JSON; keeping recipe details: {exc}")
        return None


def extract_recipe_from_json_ld(data: Any) -> Optional[Dict]:
    """Extract recipe data from various JSON-LD formats"""
    # If it's a dict with @type
    if isinstance(data, dict):
        types = data.get("@type", [])
        # Handle multiple types
        if isinstance(types, list) and "Recipe" in types:
            return data
        elif types == "Recipe":
            return data
        for key in ("@graph", "mainEntity"):
            if key in data:
                recipe = extract_recipe_from_json_ld(data[key])
                if recipe:
                    return recipe

    # If it's an array
    elif isinstance(data, list):
        for item in data:
            recipe = extract_recipe_from_json_ld(item)
            if recipe:
                return recipe

    return None


def _extract_instructions(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value for text in _extract_instructions(item)]
    if isinstance(value, dict):
        text = value.get("text") or value.get("name")
        if isinstance(text, str) and text.strip():
            return [text]
        return _extract_instructions(value.get("itemListElement", []))
    return []


def scrape_allrecipes(url: str) -> Optional[Dict]:
    """Scrape recipe details, its most helpful review, and featured tweaks."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        with requests.Session() as session:
            # The review POST only reads deferred data, so retrying it is safe.
            retry = Retry(
                total=2,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)

            response = session.get(url, headers=headers, timeout=(5, 20))
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            recipe = None
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    recipe = extract_recipe_from_json_ld(
                        json.loads(script.string or script.get_text())
                    )
                except (TypeError, json.JSONDecodeError):
                    continue
                if recipe:
                    break
            if not recipe:
                print("Recipe JSON-LD missing or invalid; returning partial details")

            title = recipe.get("name") if recipe else None
            if not title and soup.find("h1"):
                title = soup.find("h1").get_text(" ", strip=True)
            ingredients = (recipe or {}).get("recipeIngredient", [])
            if isinstance(ingredients, str):
                ingredients = [ingredients]
            elif not isinstance(ingredients, list):
                ingredients = []

            instructions = _extract_instructions(
                (recipe or {}).get("recipeInstructions", [])
            )

            payload = _request_reviews_model(session, url, soup, headers)
            feedback = extract_feedback_from_model(payload)
            if payload is None:
                print("Review data unavailable; returning recipe details only")
            recipe_id = re.search(r"/recipe/(\d+)", url)
            recipe_yield, servings = _parse_yield((recipe or {}).get("recipeYield"))
            return {
                "recipe_id": recipe_id.group(1) if recipe_id else "unknown",
                "title": title,
                "ingredients": ingredients,
                "instructions": instructions,
                "prep_time": (recipe or {}).get("prepTime"),
                "cook_time": (recipe or {}).get("cookTime"),
                "total_time": (recipe or {}).get("totalTime"),
                "servings": servings,
                "yield": recipe_yield,
                **feedback,
            }

    except requests.RequestException as e:
        print(f"Recipe request failed for {url}: {e}")
        return None
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None


def save_recipe_data(recipe_data: Dict, filename: str = None) -> str:
    """
    Save recipe data to a JSON file.

    Args:
        recipe_data: Dictionary containing recipe data
        filename: Optional filename, defaults to a recipe ID and title slug

    Returns:
        Path to saved file
    """
    if filename is None:
        title_slug = re.sub(r"[^a-z0-9]+", "-", recipe_data.get("title", "").lower())[
            :50
        ]
        filename = (
            f"data/recipe_{recipe_data.get('recipe_id', 'unknown')}_"
            f"{title_slug or 'unknown'}.json"
        )

    # Create data directory if it doesn't exist
    import os

    os.makedirs("data", exist_ok=True)

    filepath = filename if "/" in filename else f"data/{filename}"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(recipe_data, f, indent=2, ensure_ascii=False)

    print(f"Saved recipe data to {filepath}")
    return filepath


def main():
    """Scrape and save one example recipe."""
    test_url = "https://www.allrecipes.com/recipe/10813/best-chocolate-chip-cookies/"
    recipe_data = scrape_allrecipes(test_url)
    if not recipe_data:
        print("Scrape failed")
        return

    output_file = save_recipe_data(recipe_data)
    print(f"Saved {recipe_data.get('title', 'recipe')} to {output_file}")


if __name__ == "__main__":
    main()
