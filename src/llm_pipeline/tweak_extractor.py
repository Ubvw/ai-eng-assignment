"""
Step 1: Tweak Extraction & Parsing

This module extracts structured modifications from review text using LLM processing.
It converts natural language descriptions of recipe changes into structured
ModificationObject instances.
"""

import json
import os
from typing import Optional

from loguru import logger
from openai import OpenAI
from pydantic import ValidationError

from .models import ModificationObject, Recipe, Review
from .modification_classifier import has_modification
from .prompts import build_simple_prompt
from .classification import ReviewClassifier


class TweakExtractor:
    """Extracts structured modifications from review text using LLM processing."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the TweakExtractor.

        Args:
            api_key: API key (defaults to OPENROUTER_API_KEY, then OPENAI_API_KEY)
            model: OpenRouter model (defaults to OPENAI_MODEL or openai/gpt-6-luna)
        """
        self.client = OpenAI(
            api_key=(
                api_key
                or os.getenv("OPENROUTER_API_KEY")
                or os.getenv("OPENAI_API_KEY")
            ),
            base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
            max_retries=0,
        )
        self.model = model or os.getenv("OPENAI_MODEL", "openai/gpt-6-luna")
        self.classifier = ReviewClassifier(self.client, self.model)
        logger.info(f"Initialized TweakExtractor with model: {model}")

    def extract_modification(
        self,
        review: Review,
        recipe: Recipe,
        max_retries: int = 2,
    ) -> Optional[ModificationObject]:
        """
        Extract a structured modification from a review.

        Args:
            review: Review object containing modification text
            recipe: Original recipe being modified
            max_retries: Number of retry attempts if parsing fails

        Returns:
            ModificationObject if extraction successful, None otherwise
        """
        # Build the prompt - use simple prompt to avoid format string issues
        prompt = build_simple_prompt(
            review.text, recipe.title, recipe.ingredients, recipe.instructions
        )

        logger.debug(
            "Extracting modification from review: {}...".format(review.text[:100])
        )

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,  # Low temperature for consistent extractions
                    max_tokens=16384,
                    extra_body={"reasoning": {"enabled": True}},
                )

                raw_output = response.choices[0].message.content
                logger.debug(f"LLM raw output: {raw_output}")

                # Check if we got a response
                if not raw_output:
                    logger.warning(f"Attempt {attempt + 1}: Empty response from LLM")
                    continue

                # Parse and validate the JSON response
                modification_data = json.loads(raw_output)
                modification = ModificationObject(**modification_data)

                logger.info(
                    f"Successfully extracted {modification.modification_type} "
                    f"modification with {len(modification.edits)} edits"
                )
                return modification

            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1}: Failed to parse JSON: {e}")
                if attempt == max_retries:
                    logger.error(f"Max retries reached. Raw output: {raw_output}")

            except ValidationError as e:
                logger.warning(f"Attempt {attempt + 1}: Validation error: {e}")
                if attempt == max_retries:
                    logger.error(
                        f"Max retries reached. Invalid data: {modification_data}"
                    )

            except Exception as e:
                logger.error(f"Attempt {attempt + 1}: Unexpected error: {e}")
                if attempt == max_retries:
                    return None

        return None

    def extract_single_modification(
        self, reviews: list[Review], recipe: Recipe
    ) -> tuple[ModificationObject, Review] | tuple[None, None]:
        """
        Try reviews in order, allowing featured tweaks to follow the top review.

        Args:
            reviews: List of reviews to choose from
            recipe: Original recipe being modified

        Returns:
            Tuple of (ModificationObject, source_Review) if successful, (None, None) otherwise
        """
        for review in reviews:
            if not has_modification(review.text):
                logger.info("Skipping review without a likely recipe modification")
                continue
            logger.info(f"Trying review: {review.text[:100]}...")
            modification = self.extract_modification(review, recipe)
            if modification:
                logger.info("Successfully extracted modification from review")
                return modification, review

        logger.warning("No modification could be extracted from the review candidates")
        return None, None

    def test_extraction(
        self, review_text: str, recipe_data: dict
    ) -> Optional[ModificationObject]:
        """
        Test extraction with raw text and recipe data.

        Args:
            review_text: Raw review text
            recipe_data: Raw recipe dictionary

        Returns:
            ModificationObject if successful
        """
        review = Review(text=review_text)
        recipe = Recipe(
            recipe_id=recipe_data.get("recipe_id", "test"),
            title=recipe_data.get("title", "Test Recipe"),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
        )

        return self.extract_modification(review, recipe)
