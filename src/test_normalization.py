"""Offline checks for the Stage 2 loader boundary."""

import json
import unittest
from pathlib import Path

from llm_pipeline.pipeline import LLMAnalysisPipeline


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / ".scratch" / "recipe-enhancement-pipeline" / "fixtures" / "stage-1"


class NormalizationTests(unittest.TestCase):
    def load_fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_live_scrape_contract_and_legacy_projection(self):
        raw = self.load_fixture("recipe_10813_live.json")
        normalized = LLMAnalysisPipeline.parse_normalized_recipe_data(raw)
        recipe = normalized["recipe"]
        self.assertEqual(len(recipe["ingredients"]), 11)
        self.assertEqual(len(recipe["instructions"]), 9)
        self.assertEqual(recipe["ingredients"][2]["text"], "1 cup packed brown sugar")
        self.assertEqual(recipe["ingredients"][2]["name"], "packed brown sugar")
        self.assertEqual(recipe["ingredients"][7]["quantity"], "1/2")
        self.assertEqual(recipe["prep_time"], "PT20M")
        self.assertEqual(normalized["review_candidates"][0]["source"], "primary")
        self.assertEqual(normalized["review_candidates"][0]["helpful_votes"], 14241)
        self.assertEqual([row["helpful_votes"] for row in normalized["review_candidates"][1:]],
                         [702, 543, 17, 16, 12, 3, 1])

        legacy = LLMAnalysisPipeline._legacy_recipe(recipe)
        reviews = LLMAnalysisPipeline._legacy_reviews(normalized["review_candidates"])
        self.assertEqual(legacy.ingredients, raw["ingredients"])
        self.assertEqual(legacy.instructions, raw["instructions"])
        self.assertEqual(reviews[0].text, raw["most_helpful_positive_review"]["text"])
        self.assertEqual(reviews[0].helpful_votes, 14241)
        self.assertEqual(reviews[1].helpful_votes, 702)

    def test_missing_review_fixture_and_empty_pool(self):
        raw = self.load_fixture("recipe_10813_missing_reviews_edge.json")
        self.assertEqual(LLMAnalysisPipeline.parse_normalized_recipe_data(raw)["review_candidates"], [])
        empty = LLMAnalysisPipeline.parse_normalized_recipe_data(
            {"ingredients": [], "instructions": [], "featured_tweaks": []}
        )
        self.assertEqual(empty["review_candidates"], [])

    def test_exact_partial_quantities_and_candidate_order(self):
        raw = {
            "ingredients": ["1 ½-tablespoon flour", "2 eggs", "salt", "1/3 cup sugar", "¾ tsp salt"],
            "instructions": ["Mix", "Mix"],
            "featured_tweaks": [
                {"text": "low rating", "rating": 4, "helpful_count": 99},
                {"text": "known", "rating": 5, "helpful_count": 2, "extra_metadata": "kept"},
                {"text": "unknown", "rating": 5},
                {"text": "tie one", "rating": 5, "helpful_count": 2},
                {"text": "tie two", "rating": 5, "helpful_count": 2},
            ],
        }
        result = LLMAnalysisPipeline.parse_normalized_recipe_data(raw)
        rows = result["recipe"]["ingredients"]
        self.assertEqual((rows[0]["quantity"], rows[0]["unit"], rows[0]["name"]),
                         ("3/2", "tablespoon", "flour"))
        self.assertEqual((rows[1]["quantity"], rows[1]["unit"]), ("2", None))
        self.assertEqual((rows[2]["quantity"], rows[2]["name"]), (None, "salt"))
        self.assertEqual(rows[3]["quantity"], "1/3")
        self.assertNotEqual(result["recipe"]["instructions"][0]["id"],
                            result["recipe"]["instructions"][1]["id"])
        self.assertEqual([row["text"] for row in result["review_candidates"]],
                         ["known", "tie one", "tie two", "unknown"])
        self.assertEqual(result["review_candidates"][0]["metadata"]["extra_metadata"], "kept")

    def test_candidate_votes_are_ranked_globally_and_stably_across_sources(self):
        result = LLMAnalysisPipeline.parse_normalized_recipe_data({
            "ingredients": [], "instructions": [],
            "most_helpful_positive_review": {"text": "primary", "rating": 5, "helpful_votes": 2},
            "featured_tweaks": [
                {"text": "featured first tie", "rating": 5, "helpful_votes": 10},
                {"text": "featured second tie", "rating": 5, "helpful_votes": 10},
                {"text": "featured unknown", "rating": 5},
            ],
        })
        self.assertEqual([row["text"] for row in result["review_candidates"]], [
            "featured first tie", "featured second tie", "primary", "featured unknown",
        ])

    def test_known_zero_count_precedes_unknown_count(self):
        result = LLMAnalysisPipeline.parse_normalized_recipe_data({
            "ingredients": [], "instructions": [],
            "most_helpful_positive_review": {"text": "unknown", "rating": 5},
            "featured_tweaks": [{"text": "known zero", "rating": 5, "helpful_votes": 0}],
        })
        self.assertEqual([row["text"] for row in result["review_candidates"]], ["known zero", "unknown"])

    def test_duplicate_keeps_one_row_and_merges_highest_known_vote_count(self):
        result = LLMAnalysisPipeline.parse_normalized_recipe_data({
            "ingredients": [], "instructions": [],
            "most_helpful_positive_review": {
                "text": "same review", "reviewer": "A", "rating": 5, "helpful_votes": 2,
            },
            "featured_tweaks": [
                {"text": "other review", "reviewer": "B", "rating": 5, "helpful_votes": 10},
                {"text": "same review", "reviewer": "A", "rating": 5, "helpful_votes": 20},
            ],
        })
        rows = result["review_candidates"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text"], "same review")
        self.assertEqual(rows[0]["helpful_votes"], 20)
        self.assertEqual(rows[0]["id"], "review-primary-0001")


if __name__ == "__main__":
    unittest.main()
