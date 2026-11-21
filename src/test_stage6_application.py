"""Offline Stage 6 contract checks against the Stage 2 and Stage 5 shapes."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from llm_pipeline.application import apply_validated_edits
from llm_pipeline.normalization import normalize_recipe_data
from llm_pipeline.routing import route_modifications
from llm_pipeline.validation import validate_modifications


class Stage6ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.raw = {
            "recipe_id": "recipe-1", "title": "Cake", "metadata": {"tags": ["dessert"]},
            "ingredients": ["1 cup white sugar", "1 cup flour", "pinch nutmeg"],
            "instructions": ["Mix the white sugar and flour.", "Bake until set.", "Serve."],
            "most_helpful_positive_review": {
                "rating": 5, "text": "Half the sugar worked well. I let it cool.", "helpful_votes": 10,
            },
            "featured_tweaks": [{"rating": 5, "text": "It turned out well.", "helpful_votes": 1}],
        }
        normalized = normalize_recipe_data(self.raw)
        self.recipe = normalized["recipe"]
        self.review = normalized["review_candidates"][0]

    def plan(self, *mods):
        routed = route_modifications(self.recipe, {
            "decision": "propose", "review_id": self.review["id"],
            "selected_review": self.review, "modifications": list(mods),
        })
        return validate_modifications(self.raw, routed)

    def mod(self, mid, edits, quote="Half the sugar worked well."):
        return {"id": mid, "edits": edits, "evidence_quotes": [quote],
                "benefit": {"basis": "reported", "description": "The cake worked well."}}

    @staticmethod
    def reduce_sugar():
        return {"operation": "replace", "target_id": "ingredient-0001",
                "replacement_text": "1/2 cup white sugar",
                "quantity_change": {"mode": "multiply", "factor": "1/2"}}

    def test_ingredient_only_reparses_fields_and_preserves_input_and_other_content(self):
        raw_before, recipe_before = deepcopy(self.raw), deepcopy(self.recipe)
        plan = self.plan(self.mod("mod-1", [
            self.reduce_sugar(),
            {"operation": "insert", "anchor_id": "ingredient-0002", "position": "after", "text": "1 tsp vanilla"},
            {"operation": "remove", "target_id": "ingredient-0003"},
        ]))
        plan_before = deepcopy(plan)
        result = apply_validated_edits(self.recipe, plan)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["recipe"]["ingredients"], [
            {"id": "ingredient-0001", "text": "1/2 cup white sugar", "name": "white sugar",
             "quantity": "1/2", "unit": "cup"},
            recipe_before["ingredients"][1],
            {"id": "ingredient-0004", "text": "1 tsp vanilla", "name": "vanilla",
             "quantity": "1", "unit": "teaspoon"},
        ])
        self.assertEqual(result["recipe"]["instructions"], recipe_before["instructions"])
        self.assertEqual(result["recipe"]["title"], recipe_before["title"])
        self.assertEqual(result["applied_changes"], [
            {"modification_id": "mod-1", "section": "ingredients", "operation": "replace",
             "target_id": "ingredient-0001", "before": "1 cup white sugar", "after": "1/2 cup white sugar"},
            {"modification_id": "mod-1", "section": "ingredients", "operation": "insert",
             "target_id": "ingredient-0004", "anchor_id": "ingredient-0002",
             "position": "after", "after": "1 tsp vanilla"},
            {"modification_id": "mod-1", "section": "ingredients", "operation": "remove",
             "target_id": "ingredient-0003", "before": "pinch nutmeg"},
        ])
        result["recipe"]["metadata"]["tags"].append("test")
        result["selected_review"]["text"] = "Changed"
        result["modifications"][0]["evidence_quotes"].append("Changed")
        self.assertEqual(self.raw, raw_before)
        self.assertEqual(self.recipe, recipe_before)
        self.assertEqual(plan, plan_before)

    def test_instruction_only_keeps_plan_order_on_both_sides_of_removed_anchor(self):
        edits = [
            {"operation": "remove", "target_id": "instruction-0001"},
            {"operation": "insert", "anchor_id": "instruction-0001", "position": "after", "text": "Rest the batter."},
            {"operation": "insert", "anchor_id": "instruction-0001", "position": "before", "text": "Sift the flour."},
            {"operation": "insert", "anchor_id": "instruction-0001", "position": "after", "text": "Pour into a pan."},
            {"operation": "insert", "anchor_id": "instruction-0001", "position": "before", "text": "Stir in the sugar."},
            {"operation": "replace", "target_id": "instruction-0002", "replacement_text": "Bake until golden."},
        ]
        plan = self.plan(self.mod("mod-1", edits))
        result = apply_validated_edits(self.recipe, plan)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["recipe"]["ingredients"], self.recipe["ingredients"])
        self.assertEqual(result["recipe"]["instructions"], [
            {"id": "instruction-0005", "text": "Sift the flour."},
            {"id": "instruction-0007", "text": "Stir in the sugar."},
            {"id": "instruction-0004", "text": "Rest the batter."},
            {"id": "instruction-0006", "text": "Pour into a pan."},
            {"id": "instruction-0002", "text": "Bake until golden."},
            self.recipe["instructions"][2],
        ])
        self.assertEqual(result, apply_validated_edits(self.recipe, plan))

    def test_mixed_plan_carries_group_order_verified_evidence_and_actual_changes(self):
        groups = [
            self.mod("sugar", [self.reduce_sugar(), {
                "operation": "replace", "target_id": "instruction-0001",
                "replacement_text": "Mix the white sugar and flour thoroughly.",
            }]),
            self.mod("cool", [{
                "operation": "insert", "anchor_id": "instruction-0002",
                "position": "after", "text": "Let cool.",
            }], quote="I let it cool."),
        ]
        result = apply_validated_edits(self.recipe, self.plan(*groups))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["selected_review"], self.review)
        for applied, proposed in zip(result["modifications"], groups, strict=True):
            self.assertEqual(applied["id"], proposed["id"])
            self.assertEqual(applied["review_id"], self.review["id"])
            self.assertEqual(applied["benefit"], proposed["benefit"])
            self.assertEqual(applied["evidence_quotes"], proposed["evidence_quotes"])
        self.assertEqual(result["modifications"][0]["applied_changes"], result["applied_changes"][:2])
        self.assertEqual(result["modifications"][1]["applied_changes"], result["applied_changes"][2:])
        self.assertEqual([(item["modification_id"], item["section"]) for item in result["applied_changes"]],
                         [("sugar", "ingredients"), ("sugar", "instructions"), ("cool", "instructions")])

    def test_group_boundaries_are_preserved_even_if_proposal_ids_repeat(self):
        plan = self.plan(self.mod("m", [self.reduce_sugar()]), self.mod("m", [{
            "operation": "insert", "anchor_id": "instruction-0002", "position": "after", "text": "Let cool.",
        }], quote="I let it cool."))
        result = apply_validated_edits(self.recipe, plan)
        self.assertEqual([group["applied_changes"] for group in result["modifications"]],
                         [[result["applied_changes"][0]], [result["applied_changes"][1]]])
        self.assertEqual(result["modifications"][1]["evidence_quotes"], ["I let it cool."])

    def test_unexpected_error_after_prior_edit_does_not_return_a_partial_recipe(self):
        recipe_before = deepcopy(self.recipe)
        plan = self.plan(self.mod("mix", [
            {"operation": "replace", "target_id": "instruction-0001", "replacement_text": "Mix thoroughly."},
            self.reduce_sugar(),
        ]))
        plan_before = deepcopy(plan)
        with patch("llm_pipeline.application._ingredient", side_effect=RuntimeError("injected apply failure")):
            result = apply_validated_edits(self.recipe, plan)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["recipe"])
        self.assertEqual(result["modifications"], [])
        self.assertEqual(result["applied_changes"], [])
        self.assertEqual(self.recipe, recipe_before)
        self.assertEqual(plan, plan_before)
        self.assertEqual(result["diagnostics"][-1], {
            "review_id": self.review["id"], "modification_id": "mix", "section": "ingredients",
            "operation": "replace", "target": "ingredient-0001", "reason": "RuntimeError: injected apply failure",
        })

    def test_rejects_mismatched_recipe_and_stale_snapshot_for_the_same_id(self):
        plan = self.plan(self.mod("sugar", [self.reduce_sugar()]))
        other_recipe = {**self.recipe, "recipe_id": "recipe-2"}
        wrong_recipe = apply_validated_edits(other_recipe, plan)
        self.assertEqual(wrong_recipe["status"], "failed")
        self.assertIn("recipe ID", wrong_recipe["diagnostics"][-1]["reason"])
        stale = deepcopy(self.recipe)
        stale["ingredients"][0]["text"] = "1 cup brown sugar"
        stale_result = apply_validated_edits(stale, plan)
        self.assertEqual(stale_result["status"], "failed")
        self.assertEqual(stale_result["diagnostics"][-1]["target"], "ingredient-0001")
        self.assertIn("source snapshot", stale_result["diagnostics"][-1]["reason"])

    def test_empty_and_noop_are_unchanged_but_continuation_and_failure_are_distinct(self):
        empty = validate_modifications(self.raw, {"status": "exhausted", "modifications": []})
        noop = self.plan(self.mod("noop", [{
            "operation": "replace", "target_id": "instruction-0001",
            "replacement_text": self.recipe["instructions"][0]["text"],
        }]))
        self.assertEqual(noop["status"], "validated")
        for plan in (empty, noop):
            unchanged = apply_validated_edits(self.recipe, plan)
            self.assertEqual(unchanged["status"], "unchanged")
            self.assertEqual(unchanged["recipe"], self.recipe)
            self.assertIsNot(unchanged["recipe"], self.recipe)
            self.assertEqual(unchanged["modifications"], [])
            self.assertEqual(unchanged["applied_changes"], [])

        continuation = self.plan(self.mod("invalid", [self.reduce_sugar()], quote="Not in the review."))
        pending = apply_validated_edits(self.recipe, continuation)
        self.assertEqual(pending["status"], "continue")
        self.assertIsNone(pending["recipe"])
        self.assertEqual(pending["next_review"], continuation["next_review"])
        self.assertEqual(pending["diagnostics"], continuation["diagnostics"])

        failed_plan = validate_modifications(self.raw, {"status": "failed"})
        failed = apply_validated_edits(self.recipe, failed_plan)
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["recipe"])
        self.assertEqual(failed["diagnostics"], failed_plan["diagnostics"])

    def test_offline_cli_logs_file_review_and_failed_operation(self):
        plan = self.plan(self.mod("reduce-sugar", [self.reduce_sugar()]))
        self.raw["ingredients"][0] = "1 cup brown sugar"
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as folder:
            raw_path, plan_path = Path(folder) / "raw.json", Path(folder) / "stage5.json"
            raw_path.write_text(json.dumps(self.raw), encoding="utf-8")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            run = subprocess.run(
                [sys.executable, str(root / "src" / "test_pipeline.py"), "stage6", str(raw_path), str(plan_path)],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
            )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "failed")
        self.assertIn("raw.json", run.stderr)
        self.assertIn("review=review-primary-0001", run.stderr)
        self.assertIn("modification=reduce-sugar section=ingredients operation=replace target=ingredient-0001",
                      run.stderr)

    def test_offline_cli_json_round_trips_unicode_when_redirected(self):
        self.raw["title"] = "Crème brûlée ® ⅓"
        empty = validate_modifications(self.raw, {"status": "exhausted", "modifications": []})
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as folder:
            raw_path, plan_path = Path(folder) / "raw.json", Path(folder) / "stage5.json"
            raw_path.write_text(json.dumps(self.raw), encoding="utf-8")
            plan_path.write_text(json.dumps(empty), encoding="utf-8")
            run = subprocess.run(
                [sys.executable, str(root / "src" / "test_pipeline.py"), "stage6", str(raw_path), str(plan_path)],
                cwd=root, capture_output=True,
            )
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["recipe"]["title"], self.raw["title"])


if __name__ == "__main__":
    unittest.main()
