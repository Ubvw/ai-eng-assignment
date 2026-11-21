"""Offline Stage 5 contract checks."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from llm_pipeline.normalization import normalize_recipe_data
from llm_pipeline.routing import route_modifications
from llm_pipeline.validation import validate_modifications


class Stage5ValidationTests(unittest.TestCase):
    def setUp(self):
        self.raw = {"recipe_id": "r", "ingredients": ["1 cup white sugar", "1 cup flour"],
                    "instructions": ["Mix white sugar and flour", "Bake until set"],
                    "most_helpful_positive_review": {"text": "I used half as much white sugar and it was great.", "rating": 5, "helpful_votes": 8},
                    "featured_tweaks": [{"text": "I added vanilla", "rating": 5, "helpful_votes": 4}]}
        self.recipe = normalize_recipe_data(self.raw)["recipe"]
        self.review = normalize_recipe_data(self.raw)["review_candidates"][0]

    def routed(self, mods):
        return route_modifications(self.recipe, {"decision": "propose", "review_id": self.review["id"],
            "selected_review": {"id": self.review["id"]}, "modifications": mods})

    def mod(self, mid, edits, quote="half as much white sugar"):
        return {"id": mid, "evidence_quotes": [quote], "benefit": {"basis": "inferred", "description": "better balance"}, "edits": edits}

    def replace_sugar(self, quantity, quantity_change=None):
        edit = {"operation": "replace", "target_id": "ingredient-0001", "replacement_text": f"{quantity} cup white sugar"}
        if quantity_change is not None:
            edit["quantity_change"] = quantity_change
        return edit

    def test_exact_quote_and_wrong_quote(self):
        output = validate_modifications(self.raw, self.routed([self.mod("ok", [self.replace_sugar("1/2", {"mode": "multiply", "factor": "1/2"})])]))
        self.assertEqual([m["id"] for m in output["modifications"]], ["ok"])
        output = validate_modifications(self.raw, self.routed([self.mod("bad", [self.replace_sugar("1/2", {"mode": "multiply", "factor": "1/2"})], "I used half the sugar")]))
        self.assertEqual(output["modifications"], [])
        self.assertIn("verbatim", output["diagnostics"][-1]["reason"])

    def test_exact_arithmetic_negative_and_unsupported_conversion(self):
        cases = [("1/2", {"mode": "multiply", "factor": "1/2"}, True),
                 ("1/3", {"mode": "multiply", "factor": "1/2"}, False),
                 ("-1/2", {"mode": "subtract", "amount": "3/2", "unit": "cup"}, False),
                 ("8 ounces", {"mode": "multiply", "factor": "1/2"}, False)]
        for value, change, valid in cases:
            with self.subTest(value=value):
                result = validate_modifications(self.raw, self.routed([self.mod("m", [self.replace_sugar(value, change)])]))
                self.assertEqual(bool(result["modifications"]), valid)

    def test_quantity_change_without_arithmetic_is_rejected(self):
        result = validate_modifications(self.raw, self.routed([self.mod("m", [self.replace_sugar("1/2")])]))
        self.assertIn("explicit supported", result["diagnostics"][-1]["reason"])

    def test_observable_instruction_cue_and_evidence_supported_time(self):
        cue = self.mod("cue", [{"operation": "replace", "target_id": "instruction-0002", "replacement_text": "Bake until firm"}], "half as much white sugar")
        result = validate_modifications(self.raw, self.routed([cue]))
        self.assertEqual([m["id"] for m in result["modifications"]], ["cue"])
        self.raw["most_helpful_positive_review"]["text"] += " Bake for 12 minutes."
        self.review = normalize_recipe_data(self.raw)["review_candidates"][0]
        timed = self.mod("time", [{"operation": "replace", "target_id": "instruction-0002", "replacement_text": "Bake for 12 minutes"}], "Bake for 12 minutes")
        self.assertTrue(validate_modifications(self.raw, self.routed([timed]))["modifications"])
        timed["edits"][0]["replacement_text"] = "Bake for 15 minutes"
        self.assertFalse(validate_modifications(self.raw, self.routed([timed]))["modifications"])

    def test_dangling_ingredient_requires_coordinated_instruction_edit(self):
        edit = {"operation": "remove", "target_id": "ingredient-0001"}
        bad = validate_modifications(self.raw, self.routed([self.mod("remove", [edit])]))
        self.assertEqual(bad["modifications"], [])
        self.assertIn("dangling", bad["diagnostics"][-1]["reason"])
        coordinated = self.mod("linked", [edit, {"operation": "replace", "target_id": "instruction-0001", "replacement_text": "Mix flour"}])
        good = validate_modifications(self.raw, self.routed([coordinated]))
        self.assertEqual([m["id"] for m in good["modifications"]], ["linked"])

    def test_independent_groups_survive_invalid_group_and_conflict_first_wins(self):
        mods = [self.mod("invalid", [self.replace_sugar("1/2")]),
                self.mod("first", [{"operation": "replace", "target_id": "instruction-0002", "replacement_text": "Bake until golden"}]),
                self.mod("later", [{"operation": "replace", "target_id": "instruction-0002", "replacement_text": "Bake until firm"}]),
                self.mod("independent", [{"operation": "replace", "target_id": "ingredient-0002", "replacement_text": "2 cups flour",
                                          "quantity_change": {"mode": "multiply", "factor": "2"}}])]
        result = validate_modifications(self.raw, self.routed(mods))
        self.assertEqual([m["id"] for m in result["modifications"]], ["first", "independent"])
        self.assertEqual(result["diagnostics"][0]["modification_id"], "invalid")
        conflict = next(d for d in result["diagnostics"] if d["modification_id"] == "later")
        self.assertIn("first", conflict["reason"])

    def test_all_rejected_advances_to_next_ranked_candidate_and_empty_is_success(self):
        rejected = validate_modifications(self.raw, self.routed([self.mod("bad", [self.replace_sugar("1/2")])]))
        self.assertEqual(rejected["status"], "continue")
        self.assertEqual(rejected["next_review"]["source"], "featured")
        empty = validate_modifications({"recipe_id": "none", "ingredients": [], "instructions": []},
                                       {"status": "exhausted", "modifications": [], "diagnostics": []})
        self.assertEqual(empty["status"], "empty")

    def test_prior_routing_diagnostics_are_preserved(self):
        stage4 = self.routed([])
        stage4["diagnostics"] = [{"review_id": self.review["id"], "modification_id": "routed-bad", "reason": "unknown target"}]
        result = validate_modifications(self.raw, stage4)
        self.assertEqual(result["diagnostics"][0]["modification_id"], "routed-bad")

    def test_offline_stage5_cli_emits_json_and_continuation_exit(self):
        root = Path(__file__).resolve().parents[1]
        stage4 = self.routed([self.mod("bad", [self.replace_sugar("1/2")])])
        with tempfile.TemporaryDirectory() as folder:
            raw_path, result_path = Path(folder) / "raw.json", Path(folder) / "stage4.json"
            raw_path.write_text(json.dumps(self.raw), encoding="utf-8")
            result_path.write_text(json.dumps(stage4), encoding="utf-8")
            run = subprocess.run([sys.executable, "test_pipeline.py", "stage5", str(raw_path), str(result_path)],
                                 cwd=root / "src", capture_output=True, text=True)
        self.assertEqual(run.returncode, 3, run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "continue")
        self.assertIn("modification=bad", run.stderr)


if __name__ == "__main__":
    unittest.main()
