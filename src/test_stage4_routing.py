"""Offline Stage 4 exact-ID routing checks."""
import json
import unittest
from pathlib import Path

from llm_pipeline.normalization import normalize_recipe_data
from llm_pipeline.routing import route_modifications


class Stage4RoutingTests(unittest.TestCase):
    def setUp(self):
        self.recipe = normalize_recipe_data({
            "recipe_id": "r", "ingredients": ["1 cup white sugar", "1 cup brown sugar"],
            "instructions": ["Mix ingredients", "Bake until set"],
        })["recipe"]
        self.review = {"id": "review-featured-0001", "source": "featured"}

    def test_routes_all_operations_to_exact_section_and_position(self):
        result = route_modifications(self.recipe, {
            "status": "proposal", "decision": "propose", "review_id": self.review["id"],
            "selected_review": self.review, "modifications": [{"id": "m1",
                "evidence_quotes": ["I changed it"], "benefit": {"basis": "reported", "description": "better"},
                "edits": [
                    {"operation": "replace", "target_id": "ingredient-0002", "replacement_text": "2 cups brown sugar"},
                    {"operation": "remove", "target_id": "instruction-0001"},
                    {"operation": "insert", "anchor_id": "ingredient-0001", "position": "before", "text": "Oil"},
                    {"operation": "insert", "anchor_id": "instruction-0002", "position": "after", "text": "Cool"},
                ]}],
        })
        edits = result["modifications"][0]["edits"]
        self.assertEqual([(e["section"], e["index"]) for e in edits],
                         [("ingredients", 1), ("instructions", 0), ("ingredients", 0), ("instructions", 1)])
        self.assertEqual(result["modifications"][0]["benefit"]["basis"], "reported")
        self.assertEqual(result["modifications"][0]["selected_review"], self.review)
        self.assertEqual(edits[0]["matched_record"]["text"], "1 cup brown sugar")

    def test_rejects_bad_group_but_keeps_independent_group_and_does_not_pad_ids(self):
        result = route_modifications(self.recipe, {"decision": "propose", "review_id": "rv",
            "selected_review": self.review, "modifications": [
                {"id": "bad", "edits": [{"operation": "remove", "target_id": "ingredient-2"}]},
                {"id": "good", "evidence_quotes": ["quote"],
                 "benefit": {"basis": "inferred", "description": "benefit"},
                 "edits": [{"operation": "replace", "target_id": "instruction-0002", "replacement_text": "Bake."}]},
                {"id": "malformed", "edits": [{"operation": "insert", "anchor_id": "ingredient-0001", "position": "middle", "text": "x"}]},
            ]})
        self.assertEqual([m["id"] for m in result["modifications"]], ["good"])
        self.assertEqual([d["modification_id"] for d in result["diagnostics"]], ["bad", "malformed"])
        self.assertIn("unknown target ID 'ingredient-2'", result["diagnostics"][0]["reason"])

    def test_historical_ho_ho_cake_zero_padding_mismatch_is_diagnostic(self):
        root = Path(__file__).resolve().parents[1]
        recipe = normalize_recipe_data(json.loads((root / "data/test_data/recipe_8091.json").read_text(encoding="utf-8")))["recipe"]
        stage3 = json.loads((root / "data/stage3_test/recipe_8091.json").read_text(encoding="utf-8"))
        result = route_modifications(recipe, stage3)
        self.assertIn("modification-1", [m["id"] for m in result["modifications"]])
        self.assertTrue(any("ingredient-7" in item["reason"] for item in result["diagnostics"]))
        self.assertNotIn("modification-3", [m["id"] for m in result["modifications"]])

    def test_non_proposal_routes_empty(self):
        result = route_modifications(self.recipe, {"status": "exhausted", "decision": "skip"})
        self.assertEqual(result["modifications"], [])
        self.assertEqual(result["diagnostics"], [])

    def test_duplicate_ids_are_reported_as_ambiguous(self):
        recipe = {"ingredients": [{"id": "same", "text": "A"}],
                  "instructions": [{"id": "same", "text": "B"}]}
        result = route_modifications(recipe, {"decision": "propose", "modifications": [
            {"id": "m", "edits": [{"operation": "remove", "target_id": "same"}]}
        ]})
        self.assertEqual(result["modifications"], [])
        self.assertIn("ambiguous target ID", result["diagnostics"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
