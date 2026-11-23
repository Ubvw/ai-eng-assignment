"""
LLM Analysis Pipeline - Main Orchestrator

This module coordinates the complete 3-step pipeline:
1. Extract modifications from reviews
2. Apply modifications to recipes
3. Generate enhanced recipes with attribution

Processes recipe data from scraped JSON files and outputs enhanced recipes.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger

from .enhanced_recipe_generator import EnhancedRecipeGenerator
from .models import EnhancedRecipe, Recipe, Review
from .normalization import normalize_recipe_data
from .recipe_modifier import RecipeModifier
from .tweak_extractor import TweakExtractor
from .classification import ClassificationFailure
from .application import apply_validated_edits
from .generation import generate_final_recipe
from .routing import route_modifications
from .validation import validate_modifications


class LLMAnalysisPipeline:
    """Complete pipeline for analyzing recipes and generating enhanced versions."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        output_dir: str = "data/enhanced",
        pipeline_version: str = "1.0.0",
    ):
        """
        Initialize the complete LLM Analysis Pipeline.

        Args:
            openai_api_key: OpenAI API key (loads from env if not provided)
            output_dir: Directory to save enhanced recipes
            pipeline_version: Version identifier for tracking
        """
        # Load environment variables
        load_dotenv()

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize pipeline components
        self.tweak_extractor = TweakExtractor(api_key=openai_api_key)
        self.recipe_modifier = RecipeModifier()
        self.enhanced_generator = EnhancedRecipeGenerator(
            pipeline_version=pipeline_version
        )

        logger.info(f"Initialized LLM Analysis Pipeline v{pipeline_version}")
        logger.info(f"Output directory: {self.output_dir}")

    def load_recipe_data(self, file_path: str) -> Dict[str, Any]:
        """
        Load recipe data from JSON file.

        Args:
            file_path: Path to recipe JSON file

        Returns:
            Recipe data dictionary
        """
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def parse_recipe_data(self, recipe_data: Dict[str, Any]) -> Recipe:
        """
        Parse raw recipe data into Recipe object.

        Args:
            recipe_data: Raw recipe data from JSON

        Returns:
            Recipe object
        """
        return self._legacy_recipe(self.parse_normalized_recipe_data(recipe_data)["recipe"])

    @staticmethod
    def parse_normalized_recipe_data(recipe_data: Dict[str, Any]) -> Dict[str, Any]:
        """Expose the canonical Stage 2 contract: recipe rows and review candidates."""
        return normalize_recipe_data(recipe_data)

    def classify_recipe_file(self, recipe_file: str) -> Dict[str, Any]:
        """Run Stage 3 across normalized candidates and return its typed result as JSON data."""
        input_path = Path(recipe_file).resolve()
        logger.info(f"Stage 3 input file: {input_path}")
        data = self.load_recipe_data(recipe_file)
        normalized = self.parse_normalized_recipe_data(data)
        recipe = normalized["recipe"]
        candidates = normalized["review_candidates"]
        recipe_id = recipe.get("recipe_id", "unknown")
        logger.info(f"Stage 3 recipe {recipe_id}: {len(candidates)} candidate(s)")
        if not candidates:
            logger.info(f"Stage 3 recipe {recipe_id}: no eligible review candidates")
            return {
                "status": "exhausted",
                "reason": "No eligible review candidates were available.",
                "selected_review": None,
                "skipped_reviews": [],
                "failures": [],
            }

        skipped_reviews = []
        for review in candidates:
            details = _stage3_review_details(review)
            selected_review = _stage3_review_metadata(review)
            logger.info(f"Stage 3 considering candidate {details}: classifying")
            try:
                result = self.tweak_extractor.classifier.classify(
                    recipe, review,
                    on_retry=lambda attempt, reason: logger.warning(
                        f"Stage 3 review={review['id']} source={review['source']}: retry {attempt} ({reason})"
                    ),
                )
            except ClassificationFailure as exc:
                logger.error(f"Stage 3 {details}: provider/contract failure: {exc}")
                return {
                    "status": "failed",
                    "failures": [{"review_id": review["id"], "error": str(exc)}],
                    "selected_review": selected_review,
                    "skipped_reviews": skipped_reviews,
                }

            payload = result.model_dump(mode="json")
            if result.decision == "skip":
                skipped_reviews.append({
                    "review_id": review["id"],
                    "source": review["source"],
                    "reason": result.reason,
                })
                logger.info(f"Stage 3 {details}: semantic skip; checking next ranked candidate")
                continue

            logger.info(
                f"Stage 3 {details}: proposed {len(result.modifications)} modification(s)"
            )
            return {
                "status": "proposal",
                **payload,
                "selected_review": selected_review,
                "skipped_reviews": skipped_reviews,
                "failures": [],
            }

        logger.info(f"Stage 3 recipe {recipe_id}: exhausted {len(candidates)} candidate(s), no proposal")
        return {
            "status": "exhausted",
            "reason": "No eligible review candidate proposed an actionable modification.",
            "selected_review": _stage3_review_metadata(candidates[0]),
            "skipped_reviews": skipped_reviews,
            "failures": [],
        }

    def run_staged_recipe_file(self, recipe_file: str) -> Dict[str, Any]:
        """Run Stages 2–7 together, advancing candidates rejected by validation."""
        raw = self.load_recipe_data(recipe_file)
        normalized = self.parse_normalized_recipe_data(raw)
        recipe, candidates = normalized["recipe"], normalized["review_candidates"]
        diagnostics = []
        skipped_reviews = []
        review_evaluations = []

        for review in candidates:
            details = _stage3_review_details(review)
            selected_review = _stage3_review_metadata(review)
            logger.info("Pipeline considering {}", details)
            try:
                classified = self.tweak_extractor.classifier.classify(
                    recipe, review,
                    on_retry=lambda attempt, reason: logger.warning(
                        "Stage 3 review={}: retry {} ({})".format(review["id"], attempt, reason)
                    ),
                )
            except ClassificationFailure as exc:
                failure = {
                    "review_id": review["id"],
                    "reason": f"Stage 3 provider/contract failure: {exc}",
                }
                review_evaluations.append({
                    "review_id": review["id"], "source": review["source"],
                    "helpful_votes": review["helpful_votes"], "status": "failed",
                    "diagnostics": [failure],
                })
                final = generate_final_recipe({
                    "status": "failed", "recipe_id": recipe.get("recipe_id"),
                    "review_id": review["id"], "selected_review": review,
                    "diagnostics": [*diagnostics, failure],
                })
                final["review_evaluations"] = review_evaluations
                return final

            stage3_output = classified.model_dump(mode="json")
            evaluation = {
                "review_id": review["id"], "source": review["source"],
                "helpful_votes": review["helpful_votes"], "stage3": stage3_output,
            }
            if classified.decision == "skip":
                skipped_reviews.append({
                    "review_id": review["id"], "source": review["source"],
                    "reason": classified.reason,
                })
                evaluation["status"] = "skipped"
                review_evaluations.append(evaluation)
                continue

            stage3 = {
                **stage3_output,
                "selected_review": selected_review,
            }
            routed = route_modifications(recipe, stage3)
            validated = validate_modifications(raw, routed)
            evaluation.update({"stage4": routed, "stage5": validated,
                               "status": validated["status"]})
            review_evaluations.append(evaluation)
            diagnostics.extend(validated.get("diagnostics", []))
            if validated["status"] == "continue":
                logger.info("Stage 5 rejected all edits from {}; trying next candidate", review["id"])
                continue
            if validated["status"] == "failed":
                final = generate_final_recipe({
                    "status": "failed", "recipe_id": recipe.get("recipe_id"),
                    "review_id": review["id"], "selected_review": review,
                    "diagnostics": diagnostics,
                })
                final["review_evaluations"] = review_evaluations
                return final

            validated["diagnostics"] = diagnostics
            applied = apply_validated_edits(recipe, validated)
            applied["diagnostics"] = diagnostics
            final = generate_final_recipe(applied)
            final["skipped_reviews"] = skipped_reviews
            final["review_evaluations"] = review_evaluations
            return final

        empty_plan = {
            "status": "empty", "recipe_id": recipe.get("recipe_id"),
            "review_id": None, "selected_review": None,
            "modifications": [], "diagnostics": diagnostics,
        }
        final = generate_final_recipe(apply_validated_edits(recipe, empty_plan))
        final["skipped_reviews"] = skipped_reviews
        final["review_evaluations"] = review_evaluations
        return final
    @staticmethod
    def _legacy_recipe(normalized: Dict[str, Any]) -> Recipe:
        """Project the canonical Stage 2 contract for existing pipeline callers."""
        return Recipe(
            recipe_id=str(normalized.get("recipe_id", "unknown")),
            title=normalized.get("title", "Unknown Recipe"),
            ingredients=[row["text"] for row in normalized["ingredients"]],
            instructions=[row["text"] for row in normalized["instructions"]],
            description=normalized.get("description"),
            servings=normalized.get("servings"),
            rating=normalized.get("rating"),
        )

    def parse_reviews_data(self, recipe_data: Dict[str, Any]) -> List[Review]:
        """
        Parse the preferred review followed by featured tweaks into Review objects.

        Args:
            recipe_data: Scraped recipe data or a legacy reviews list

        Returns:
            List of Review objects
        """
        return self._legacy_reviews(normalize_recipe_data(recipe_data)["review_candidates"])

    @staticmethod
    def _legacy_reviews(candidates: List[Dict[str, Any]]) -> List[Review]:
        return [Review(text=row["text"], rating=row["rating"], username=row["reviewer"],
                       review_id=row["id"], helpful_votes=row["helpful_votes"],
                       date=row["date"], source=row["source"], permalink=row["permalink"],
                       metadata=row["metadata"]) for row in candidates]

    def process_single_recipe(
        self, recipe_file: str, save_output: bool = True
    ) -> Optional[EnhancedRecipe]:
        """
        Process a single recipe through the complete pipeline.

        Args:
            recipe_file: Path to recipe JSON file
            save_output: Whether to save the enhanced recipe

        Returns:
            EnhancedRecipe if successful, None otherwise
        """
        try:
            logger.info(f"Processing recipe file: {recipe_file}")

            # Step 0: Load and parse data
            recipe_data = self.load_recipe_data(recipe_file)
            normalized = self.parse_normalized_recipe_data(recipe_data)
            recipe = self._legacy_recipe(normalized["recipe"])
            reviews = self._legacy_reviews(normalized["review_candidates"])

            logger.info(f"Loaded recipe: {recipe.title}")
            logger.info(f"Found {len(reviews)} review candidates")

            # Step 1: Try the most helpful review, then featured tweaks in order.
            logger.info("Step 1: Extracting a modification from review candidates...")
            modification, source_review = (
                self.tweak_extractor.extract_single_modification(reviews, recipe)
            )

            if not modification or not source_review:
                logger.warning("No modification could be extracted")
                return None

            logger.info(
                f"Successfully extracted {modification.modification_type} modification"
            )

            # Step 2: Apply modification to recipe
            logger.info("Step 2: Applying modification to recipe...")
            modified_recipe, change_records = self.recipe_modifier.apply_modification(
                recipe, modification
            )

            logger.info(
                f"Applied modification: {len(change_records)} total changes made"
            )

            # Step 3: Generate enhanced recipe with attribution
            logger.info("Step 3: Generating enhanced recipe with attribution...")

            enhanced_recipe = self.enhanced_generator.generate_enhanced_recipe(
                recipe, modified_recipe, modification, source_review, change_records
            )

            logger.info(f"Generated enhanced recipe: {enhanced_recipe.title}")

            # Save output
            if save_output:
                output_filename = f"enhanced_{recipe.recipe_id}_{recipe.title.lower().replace(' ', '-')[:30]}.json"
                output_path = self.output_dir / output_filename
                self.enhanced_generator.save_enhanced_recipe(
                    enhanced_recipe, str(output_path)
                )

            return enhanced_recipe

        except Exception as e:
            logger.error(f"Failed to process recipe {recipe_file}: {e}")
            import traceback

            traceback.print_exc()
            return None

    def process_recipe_directory(self, data_dir: str = "data") -> List[EnhancedRecipe]:
        """
        Process all recipe files in a directory.

        Args:
            data_dir: Directory containing recipe JSON files

        Returns:
            List of successfully processed EnhancedRecipe objects
        """
        data_path = Path(data_dir)
        recipe_files = list(data_path.glob("recipe_*.json"))

        logger.info(f"Found {len(recipe_files)} recipe files to process")

        enhanced_recipes = []
        for recipe_file in recipe_files:
            logger.info(f"\n{'=' * 60}")
            enhanced_recipe = self.process_single_recipe(str(recipe_file))

            if enhanced_recipe:
                enhanced_recipes.append(enhanced_recipe)
                logger.info(f"✓ Successfully processed: {enhanced_recipe.title}")
            else:
                logger.warning(f"✗ Failed to process: {recipe_file.name}")

        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"Pipeline complete: {len(enhanced_recipes)}/{len(recipe_files)} recipes successfully enhanced"
        )

        return enhanced_recipes

    def generate_summary_report(
        self, enhanced_recipes: List[EnhancedRecipe]
    ) -> Dict[str, Any]:
        """
        Generate a summary report of pipeline results.

        Args:
            enhanced_recipes: List of enhanced recipes

        Returns:
            Summary report dictionary
        """
        if not enhanced_recipes:
            return {"status": "no_recipes_processed"}

        total_modifications = sum(
            len(recipe.modifications_applied) for recipe in enhanced_recipes
        )
        total_changes = sum(
            recipe.enhancement_summary.total_changes for recipe in enhanced_recipes
        )

        change_type_counts = {}
        for recipe in enhanced_recipes:
            for change_type in recipe.enhancement_summary.change_types:
                change_type_counts[change_type] = (
                    change_type_counts.get(change_type, 0) + 1
                )

        report = {
            "pipeline_summary": {
                "recipes_processed": len(enhanced_recipes),
                "total_modifications_applied": total_modifications,
                "total_changes_made": total_changes,
                "change_type_distribution": change_type_counts,
            },
            "enhanced_recipes": [
                {
                    "recipe_id": recipe.recipe_id,
                    "title": recipe.title,
                    "modifications_count": len(recipe.modifications_applied),
                    "changes_count": recipe.enhancement_summary.total_changes,
                    "change_types": recipe.enhancement_summary.change_types,
                }
                for recipe in enhanced_recipes
            ],
        }

        return report

    def save_summary_report(
        self, enhanced_recipes: List[EnhancedRecipe], output_path: Optional[str] = None
    ) -> str:
        """
        Save pipeline summary report to JSON file.

        Args:
            enhanced_recipes: List of enhanced recipes
            output_path: Path to save report (auto-generated if None)

        Returns:
            Path to saved report
        """
        if output_path is None:
            output_path = str(self.output_dir / "pipeline_summary_report.json")

        report = self.generate_summary_report(enhanced_recipes)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved pipeline summary report to: {output_path}")
        return output_path


def _stage3_review_details(review: Dict[str, Any]) -> str:
    """Format only normalized review identifiers and compact available metadata for progress logs."""
    fields = (
        ("review", review.get("id")),
        ("source", review.get("source")),
        ("reviewer", review.get("reviewer")),
        ("rating", review.get("rating")),
        ("helpful_votes", review.get("helpful_votes")),
        ("date", review.get("date")),
    )
    return " ".join(f"{name}={value if value is not None else 'unknown'}" for name, value in fields)


def _stage3_review_metadata(review: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: review.get(key)
        for key in ("id", "source", "reviewer", "rating", "helpful_votes", "date", "permalink")
    }
