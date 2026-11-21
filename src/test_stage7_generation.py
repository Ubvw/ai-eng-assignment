"""Offline output checks through the Stage 7 API and CLI."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from llm_pipeline.application import apply_validated_edits
from llm_pipeline.generation import generate_final_recipe
from llm_pipeline.normalization import normalize_recipe_data
from llm_pipeline.routing import route_modifications
from llm_pipeline.validation import validate_modifications


class Stage7GenerationTests(unittest.TestCase):
    def setUp(self):
        self.raw = {
            "recipe_id": "cake", "title": "Crème cake", "metadata": {"servings": "4"},
            "ingredients": ["1 cup white sugar", "1 cup flour"],
            "instructions": ["Mix the sugar and flour.", "Bake until set."],
            "most_helpful_positive_review": {
                "rating": 5, "text": "½ cup sugar was perfect!  I let it cool.", "helpful_votes": 10,
            },
            "featured_tweaks": [{"rating": 5, "text": "I used another method.", "helpful_votes": 5}],
        }
        normalized = normalize_recipe_data(self.raw)
        self.recipe = normalized["recipe"]
        self.review = normalized["review_candidates"][0]
        self.sugar = {
            "id": "m", "evidence_quotes": ["½ cup sugar was perfect!"],
            "benefit": {"basis": "reported", "description": "The reviewer preferred the sweetness."},
            "edits": [{"operation": "replace", "target_id": "ingredient-0001",
                       "replacement_text": "1/2 cup white sugar",
                       "quantity_change": {"mode": "multiply", "factor": "1/2"}}],
        }
        self.cool = {
            "id": "m", "evidence_quotes": ["  I let it cool."],
            "benefit": {"basis": "inferred", "description": "Cooling may help the cake set."},
            "edits": [{"operation": "insert", "anchor_id": "instruction-0002",
                       "position": "after", "text": "Let the cake cool."}],
        }

    def apply_proposal(self, *groups):
        routed = route_modifications(self.recipe, {
            "decision": "propose", "review_id": self.review["id"], "modifications": list(groups),
        })
        return apply_validated_edits(self.recipe, validate_modifications(self.raw, routed))

    def test_actual_ingredient_and_instruction_changes_keep_grouped_review_evidence(self):
        for mods, sections in [
            ((self.sugar,), ["ingredients"]), ((self.cool,), ["instructions"]),
            ((self.sugar, self.cool), ["ingredients", "instructions"]),
        ]:
            with self.subTest(sections=sections):
                applied = self.apply_proposal(*mods)
                before = deepcopy(applied)
                applied.pop("applied_changes")  # Groups are authoritative even when IDs repeat.
                result = generate_final_recipe(applied)
                self.assertEqual(result["status"], "enhanced")
                self.assertEqual(result["recipe"], before["recipe"])
                self.assertEqual(result["selected_review"], self.review)
                self.assertEqual([group["changes"][0]["section"] for group in result["modifications"]], sections)
                self.assertEqual(result["modifications"], [
                    {"id": proposal["id"], "changes": group["applied_changes"],
                     "benefit": proposal["benefit"],
                     "evidence": [{"review_id": self.review["id"], "quote": proposal["evidence_quotes"][0]}]}
                    for proposal, group in zip(mods, before["modifications"], strict=True)
                ])
                result["recipe"]["metadata"]["servings"] = "99"
                result["modifications"][0]["changes"][0]["after"] = "Mutated"
                result["selected_review"]["text"] = "Mutated"
                before.pop("applied_changes")
                self.assertEqual(applied, before)

    def test_partial_validation_and_noop_groups_never_claim_an_improvement(self):
        bad = {**self.cool, "id": "rejected", "evidence_quotes": ["An invented quote."]}
        noop = {**self.cool, "id": "noop", "edits": [{
            "operation": "replace", "target_id": "instruction-0001",
            "replacement_text": self.recipe["instructions"][0]["text"],
        }]}
        applied = self.apply_proposal(self.sugar, bad, noop)
        applied["modifications"].append({"id": "empty", "applied_changes": []})
        result = generate_final_recipe(applied)
        self.assertEqual(result["status"], "enhanced")
        self.assertEqual(result["recipe"]["instructions"], self.recipe["instructions"])
        self.assertEqual([group["id"] for group in result["modifications"]], ["m"])
        self.assertEqual(result["diagnostics"], applied["diagnostics"])
        self.assertEqual([item["modification_id"] for item in result["diagnostics"]], ["rejected"])

    def test_exhausted_candidates_return_original_recipe_and_reason(self):
        exhausted = validate_modifications(self.raw, {"status": "exhausted", "modifications": []})
        noop = {**self.cool, "edits": [{"operation": "replace", "target_id": "instruction-0001",
                                       "replacement_text": self.recipe["instructions"][0]["text"]}]}
        for source in (apply_validated_edits(self.recipe, exhausted), self.apply_proposal(noop)):
            result = generate_final_recipe(source)
            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(result["recipe"], self.recipe)
            self.assertEqual(result["reason"], "No applicable edits were applied.")
            self.assertEqual(result["modifications"], [])
            self.assertIsNone(result["selected_review"])

    def test_failure_and_continuation_preserve_diagnostics_without_a_final_recipe(self):
        plan = validate_modifications(self.raw, {"status": "failed"})
        failed = apply_validated_edits(self.recipe, plan)
        pending = self.apply_proposal({**self.cool, "evidence_quotes": ["Not a verbatim quote."]})
        for source, status in ((failed, "failed"), (pending, "continue")):
            with self.subTest(status=status):
                result = generate_final_recipe(source)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["diagnostics"], source["diagnostics"])
                self.assertIsNone(result["recipe"])
                self.assertEqual(result["modifications"], [])
        self.assertEqual(generate_final_recipe(pending)["next_review"], pending["next_review"])
        self.assertEqual(pending["next_review"]["id"], "review-featured-0001")

    def test_invalid_saved_provenance_does_not_return_a_partial_enhancement(self):
        for invalid_field in ({"review_id": "other"}, {"evidence_quotes": ["Appended fabrication."]},
                              {"benefit": {"basis": "guessed"}}):
            with self.subTest(invalid_field=invalid_field):
                applied = self.apply_proposal(self.sugar, self.cool)
                applied["modifications"][1].update(invalid_field)
                result = generate_final_recipe(applied)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["diagnostics"][-1]["review_id"], self.review["id"])
                self.assertIsNone(result["recipe"])
                self.assertEqual(result["modifications"], [])

    def test_offline_cli_round_trips_unicode_and_returns_status_exit_codes(self):
        enhanced = self.apply_proposal(self.sugar, self.cool)
        pending = self.apply_proposal({**self.cool, "evidence_quotes": ["Not a verbatim quote."]})
        failed = {**enhanced, "status": "failed", "diagnostics": [{"reason": "Injected failure."}]}
        script = Path(__file__).resolve().with_name("test_pipeline.py")
        env = {**os.environ, "DOTENV_NO_DOTENV": "1", "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": ""}
        with TemporaryDirectory() as folder:
            input_path = Path(folder) / "stage6-result.json"
            for applied, code in ((enhanced, 0), (pending, 3), (failed, 1)):
                with self.subTest(exit_code=code):
                    input_path.write_text(json.dumps(applied, ensure_ascii=False), encoding="utf-8-sig")
                    run = subprocess.run([sys.executable, str(script), "stage7", str(input_path)],
                                         env=env, capture_output=True)
                    self.assertEqual(run.returncode, code, run.stderr)
                    self.assertEqual(json.loads(run.stdout), generate_final_recipe(applied))
                    self.assertIn(b"stage6-result.json", run.stderr)
                    self.assertIn(self.review["id"].encode(), run.stderr)
        self.assertIn(b"Injected failure.", run.stderr)


if __name__ == "__main__":
    unittest.main()
