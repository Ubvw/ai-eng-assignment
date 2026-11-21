#!/usr/bin/env python3
"""
LLM Analysis Pipeline Test Script

Run the legacy recipe pipeline or verify individual stage boundaries.

Usage:
    python test_pipeline.py single    # Test single chocolate chip cookie recipe
    python test_pipeline.py all       # Test all recipes in data directory
    python test_pipeline.py stage3 data/recipe_10813_best-chocolate-chip-cookies.json
    python test_pipeline.py stage4 data/recipe.json data/stage3-result.json
    python test_pipeline.py stage5 data/recipe.json data/stage4-result.json
    python test_pipeline.py stage6 data/recipe.json data/stage5-result.json
    python test_pipeline.py stage7 data/stage6-result.json
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

from llm_pipeline.application import apply_validated_edits
from llm_pipeline.generation import generate_final_recipe
from llm_pipeline.pipeline import LLMAnalysisPipeline
from llm_pipeline.normalization import normalize_recipe_data
from llm_pipeline.routing import route_modifications
from llm_pipeline.validation import validate_modifications
from loguru import logger

# Load environment variables from .env file
load_dotenv()


def test_single_recipe():
    """Test the pipeline with the chocolate chip cookie recipe."""

    # Check for OpenAI API key
    if not (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")):
        logger.error("No LLM API key environment variable is set")
        logger.info("Set OPENROUTER_API_KEY in .env file")
        return False

    # Initialize pipeline
    try:
        pipeline = LLMAnalysisPipeline()
        logger.info("Pipeline initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        return False

    # Test with chocolate chip cookie recipe
    recipe_file = "../data/recipe_10813_best-chocolate-chip-cookies.json"
    if not Path(recipe_file).exists():
        logger.error(f"Recipe file not found: {recipe_file}")
        return False

    logger.info(f"Testing with recipe file: {recipe_file}")

    try:
        # Process the recipe
        enhanced_recipe = pipeline.process_single_recipe(
            recipe_file=recipe_file,
            save_output=True
        )

        if enhanced_recipe:
            logger.success("✓ Single recipe test successful!")
            logger.info(f"Enhanced recipe: {enhanced_recipe.title}")
            logger.info(f"Modifications applied: {len(enhanced_recipe.modifications_applied)}")
            logger.info(f"Total changes: {enhanced_recipe.enhancement_summary.total_changes}")
            logger.info(f"Expected impact: {enhanced_recipe.enhancement_summary.expected_impact}")
            return True
        else:
            logger.error("✗ Single recipe test failed - no enhanced recipe generated")
            return False

    except Exception as e:
        logger.error(f"Single recipe test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_recipes():
    """Test the pipeline with all scraped recipes."""

    # Check for OpenAI API key
    if not (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")):
        logger.error("No LLM API key environment variable is set")
        logger.info("Set OPENROUTER_API_KEY in .env file")
        return False

    # Initialize pipeline
    try:
        pipeline = LLMAnalysisPipeline()
        logger.info("Pipeline initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        return False

    try:
        # Process all recipes
        enhanced_recipes = pipeline.process_recipe_directory(
            data_dir="../data"
        )

        # Generate summary report
        report_path = pipeline.save_summary_report(enhanced_recipes)

        logger.info(f"\n{'=' * 60}")
        logger.success("✓ All recipes test complete!")
        logger.info(f"Enhanced recipes: {len(enhanced_recipes)}")
        logger.info(f"Summary report saved to: {report_path}")

        return len(enhanced_recipes) > 0

    except Exception as e:
        logger.error(f"All recipes test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test function with mode selection."""

    usage = "Usage: python test_pipeline.py [single|all|stage3|stage4|stage5|stage6|stage7]"
    # Parse command line argument
    if len(sys.argv) < 2:
        logger.error(usage)
        logger.info("  single - Test single chocolate chip cookie recipe")
        logger.info("  all    - Test all recipes in data directory")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "stage7":
        if len(sys.argv) != 3:
            logger.error("Usage: python test_pipeline.py stage7 <stage6-result.json>")
            sys.exit(2)
        result_path = Path(sys.argv[2])
        if not result_path.is_file():
            logger.error("Stage 6 result file not found: {}", result_path)
            sys.exit(2)
        try:
            stage6_result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            logger.error("Stage 7 could not read {}: {}", result_path, exc)
            sys.exit(1)
        result = generate_final_recipe(stage6_result)
        print(json.dumps(result, indent=2))
        status = result["status"]
        if status == "failed":
            error = result["diagnostics"][-1] if result["diagnostics"] else {}
            logger.error("Stage 7 failed file={} review={}: {}", result_path, result["review_id"],
                         error.get("reason", result["reason"]))
            sys.exit(1)
        logger.info("Stage 7 {} file={} review={}: {} applied modification(s)",
                    status, result_path, result["review_id"], len(result["modifications"]))
        if status == "continue":
            sys.exit(3)
        return

    if mode == "stage4":
        if len(sys.argv) != 4:
            logger.error("Usage: python test_pipeline.py stage4 <raw-recipe.json> <stage3-result.json>")
            sys.exit(2)
        raw_path, result_path = map(Path, sys.argv[2:])
        if not raw_path.is_file() or not result_path.is_file():
            logger.error("Both raw recipe and Stage 3 result files must exist")
            sys.exit(2)
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            stage3_result = json.loads(result_path.read_text(encoding="utf-8"))
            normalized = normalize_recipe_data(raw)
            result = route_modifications(normalized["recipe"], stage3_result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            logger.info(f"Stage 4 complete: {len(result['modifications'])} routable modification(s), {len(result['diagnostics'])} diagnostic(s)")
        except Exception as e:
            logger.error(f"Stage 4 failed: {type(e).__name__}: {e}")
            sys.exit(1)
        return

    if mode == "stage5":
        if len(sys.argv) != 4:
            logger.error("Usage: python test_pipeline.py stage5 <raw-recipe.json> <stage4-result.json>")
            sys.exit(2)
        raw_path, result_path = map(Path, sys.argv[2:])
        if not raw_path.is_file() or not result_path.is_file():
            logger.error("Both raw recipe and Stage 4 result files must exist")
            sys.exit(2)
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            stage4_result = json.loads(result_path.read_text(encoding="utf-8"))
            result = validate_modifications(raw, stage4_result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            for item in result["diagnostics"]:
                logger.warning("Stage 5 rejected review={} modification={} target={}: {}",
                               item.get("review_id"), item.get("modification_id"), item.get("target"), item.get("reason"))
            logger.info("Stage 5 {}: {} valid modification(s), {} diagnostic(s)".format(
                result["status"], len(result["modifications"]), len(result["diagnostics"])))
            if result["status"] == "failed":
                sys.exit(1)
            if result["status"] == "continue":
                sys.exit(3)
        except Exception as e:
            logger.error(f"Stage 5 failed: {type(e).__name__}: {e}")
            sys.exit(1)
        return

    if mode == "stage6":
        if len(sys.argv) != 4:
            logger.error("Usage: python test_pipeline.py stage6 <raw-recipe.json> <stage5-result.json>")
            sys.exit(2)
        raw_path, result_path = map(Path, sys.argv[2:])
        if not raw_path.is_file() or not result_path.is_file():
            logger.error("Both raw recipe and Stage 5 result files must exist")
            sys.exit(2)
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            stage5_result = json.loads(result_path.read_text(encoding="utf-8"))
            logger.info("Stage 6 applying recipe={} plan={} review={}",
                        raw_path, result_path, stage5_result.get("review_id"))
            result = apply_validated_edits(normalize_recipe_data(raw)["recipe"], stage5_result)
            print(json.dumps(result, indent=2))
            if result["status"] == "failed":
                error = result["diagnostics"][-1] if result["diagnostics"] else {}
                logger.error("Stage 6 failed review={} modification={} section={} operation={} target={}: {}",
                             result["review_id"], error.get("modification_id"), error.get("section"),
                             error.get("operation"), error.get("target"), error.get("reason", "Stage 5 failed"))
                sys.exit(1)
            logger.info("Stage 6 {}: {} applied change(s)", result["status"], len(result["applied_changes"]))
            if result["status"] == "continue":
                sys.exit(3)
        except Exception as e:
            logger.error("Stage 6 failed: {}: {}", type(e).__name__, e)
            sys.exit(1)
        return

    if mode == "stage3":
        if len(sys.argv) != 3:
            logger.error("Usage: python test_pipeline.py stage3 <saved-recipe.json>")
            sys.exit(2)
        recipe_path = Path(sys.argv[2])
        if not recipe_path.is_file():
            logger.error(f"Recipe file not found: {recipe_path}")
            sys.exit(2)
        try:
            pipeline = LLMAnalysisPipeline()
            result = pipeline.classify_recipe_file(str(recipe_path))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            logger.info(f"Stage 3 complete: status={result['status']}")
            if result["status"] == "failed":
                sys.exit(1)
        except Exception as e:
            logger.error(f"Stage 3 failed: {type(e).__name__}: {e}")
            sys.exit(1)
        return

    if mode == "single":
        logger.info("Starting LLM Analysis Pipeline - Single Recipe Test")
        logger.info("=" * 60)
        success = test_single_recipe()

        logger.info("=" * 60)
        if success:
            logger.success("Single recipe test passed! ✓")
            logger.info("Check the 'data/enhanced/' directory for the enhanced recipe.")
        else:
            logger.error("Single recipe test failed! ✗")
            sys.exit(1)

    elif mode == "all":
        logger.info("Starting LLM Analysis Pipeline - All Recipes Validation")
        logger.info("=" * 60)
        success = test_all_recipes()

        logger.info("=" * 60)
        if success:
            logger.success("All recipes validation passed! ✓")
            logger.info("Check the 'data/enhanced/' directory for all enhanced recipes.")
            logger.info("Check 'data/enhanced/pipeline_summary_report.json' for detailed results.")
        else:
            logger.error("All recipes validation failed! ✗")
            sys.exit(1)

    else:
        logger.error(f"Unknown mode: {mode}")
        logger.error(usage)
        sys.exit(1)


if __name__ == "__main__":
    main()
