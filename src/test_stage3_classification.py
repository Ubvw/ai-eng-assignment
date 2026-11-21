"""Offline checks for Stage 3 provider and CLI behavior."""
import json
import os
import re
import sys
import unittest
import httpx
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from llm_pipeline.classification import ClassificationFailure, ReviewClassifier, approved_messages
from llm_pipeline.pipeline import LLMAnalysisPipeline
from openai import APITimeoutError
from loguru import logger

RECIPE = {"title": "Cookies", "ingredients": [], "instructions": []}
REVIEW = {"id": "review-x", "text": "Nice cookies", "rating": 5, "source": "primary"}
SKIP = json.dumps({"review_id": "review-x", "decision": "skip", "reason": "No change."})


class Provider:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=value))])


class Stage3Tests(unittest.TestCase):
    def run_pipeline_for_pool(self, primary=None, featured=(), outcome="skip"):
        directory = TemporaryDirectory()
        path = Path(directory.name) / "recipe.json"
        path.write_text(json.dumps({"recipe_id": "r", "ingredients": [], "instructions": [],
            "most_helpful_positive_review": primary, "featured_tweaks": list(featured)}), encoding="utf-8")
        pipeline = LLMAnalysisPipeline.__new__(LLMAnalysisPipeline)
        calls = []

        def classify(recipe, review, on_retry):
            calls.append(review)
            choice = outcome[len(calls) - 1] if isinstance(outcome, list) else outcome
            if choice == "failure":
                raise ClassificationFailure("invalid response contract; retries exhausted")
            decision = "propose" if choice == "proposal" else "skip"
            return SimpleNamespace(
                decision=decision,
                modifications=[object()] if decision == "propose" else [],
                reason=f"Model skip reason for {review['id']}" if decision == "skip" else None,
                model_dump=lambda mode: {
                    "review_id": review["id"], "decision": decision,
                    "reason": "No change." if decision == "skip" else None,
                    "modifications": [{"id": "mod-1"}] if decision == "propose" else None,
                },
            )

        pipeline.tweak_extractor = SimpleNamespace(classifier=SimpleNamespace(classify=classify))
        result = pipeline.classify_recipe_file(str(path))
        directory.cleanup()
        return result, calls

    def test_approved_messages_have_all_21_json_pairs(self):
        messages = approved_messages()
        self.assertEqual(len(messages), 43)
        self.assertEqual(sum(message["role"] == "assistant" for message in messages), 21)
        for message in messages[1:]:
            json.loads(message["content"])
        original = os.getcwd()
        try:
            os.chdir(Path(__file__).resolve().parents[1])
            self.assertEqual(len(approved_messages()), 43)
        finally:
            os.chdir(original)

    def test_approved_examples_use_canonical_padded_recipe_ids(self):
        for message in approved_messages()[1:]:
            content = json.loads(message["content"])
            if message["role"] == "user":
                recipe = content["recipe"]
                ids = [row["id"] for row in recipe["ingredients"] + recipe["instructions"]]
                self.assertTrue(all(re.fullmatch(r"(?:ingredient|instruction)-\d{4}", value) for value in ids))
            else:
                for mod in content.get("modifications", []):
                    for edit in mod["edits"]:
                        value = edit.get("anchor_id", edit.get("target_id"))
                        self.assertRegex(value, r"^(?:ingredient|instruction)-\d{4}$")

    def test_unpadded_or_unknown_edit_reference_retries(self):
        recipe = {"title": "Cookies", "ingredients": [{"id": "ingredient-0006", "text": "1 cup sugar"}],
                  "instructions": [{"id": "instruction-0001", "text": "Mix."}]}
        valid = {"review_id": "review-x", "decision": "propose", "modifications": [{
            "id": "mod-1", "evidence_quotes": ["I chilled it."],
            "benefit": {"basis": "inferred", "description": "May improve texture."},
            "edits": [{"operation": "insert", "anchor_id": "instruction-0001", "position": "before", "text": "Chill."}]}]}
        malformed = json.loads(json.dumps(valid))
        malformed["modifications"][0]["edits"][0]["anchor_id"] = "instruction-1"
        provider = Provider([json.dumps(malformed), json.dumps(valid)])
        result = ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(
            recipe, {**REVIEW, "text": "I chilled it."})
        self.assertEqual(result.decision, "propose")
        self.assertEqual(len(provider.calls), 2)

        malformed["modifications"][0]["edits"][0]["anchor_id"] = "instruction-9999"
        provider = Provider([json.dumps(malformed)] * 3)
        with self.assertRaisesRegex(ClassificationFailure, "retries exhausted"):
            ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(
                recipe, {**REVIEW, "text": "I chilled it."})

    def test_skip_and_final_live_input(self):
        provider = Provider([SKIP])
        result = ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(RECIPE, REVIEW)
        self.assertEqual(result.decision, "skip")
        messages = provider.calls[0]["messages"]
        self.assertEqual(json.loads(messages[-1]["content"]), {"recipe": RECIPE, "review": REVIEW})
        self.assertIn("I used 90 g of flour", messages[13]["content"])

    def test_bad_response_retries_twice_then_fails_operationally(self):
        provider, retries = Provider(["bad", "{}", "bad"]), []
        with self.assertRaisesRegex(ClassificationFailure, "retries exhausted"):
            ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(
                RECIPE, REVIEW, on_retry=lambda attempt, reason: retries.append(attempt))
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(retries, [1, 2])

    def test_identity_mismatch_retries_then_accepts(self):
        wrong = json.dumps({"review_id": "other", "decision": "skip", "reason": "no"})
        provider = Provider([wrong, SKIP])
        result = ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(RECIPE, REVIEW)
        self.assertEqual(result.review_id, "review-x")
        self.assertEqual(len(provider.calls), 2)

    def test_transient_timeout_retries_once_then_succeeds(self):
        provider = Provider([APITimeoutError(request=httpx.Request("POST", "https://offline.invalid")), SKIP])
        retries = []
        result = ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(
            RECIPE, REVIEW, on_retry=lambda attempt, reason: retries.append(reason))
        self.assertEqual(result.decision, "skip")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(retries, ["APITimeoutError"])

    def test_proposal_preserves_grouped_edits_and_requires_verbatim_evidence(self):
        recipe = {"title": "Cookies", "ingredients": [{"id": "ingredient-0001", "text": "1 cup sugar"}],
                  "instructions": [{"id": "instruction-0001", "text": "Mix."}]}
        payload = {"review_id": "review-x", "decision": "propose", "modifications": [{
            "id": "mod-1", "evidence_quotes": ["I chilled it."],
            "benefit": {"basis": "inferred", "description": "May reduce spreading."},
            "edits": [{"operation": "insert", "anchor_id": "instruction-0001", "position": "before", "text": "Chill."},
                      {"operation": "replace", "target_id": "instruction-0001", "replacement_text": "Bake."}]}]}
        review = {**REVIEW, "text": "I chilled it."}
        result = ReviewClassifier(Provider([json.dumps(payload)]), "offline", sleep=lambda _: None).classify(recipe, review)
        self.assertEqual(len(result.modifications[0].edits), 2)
        payload["modifications"][0]["evidence_quotes"] = ["I cooled it."]
        provider = Provider([json.dumps(payload), json.dumps(payload), json.dumps(payload)])
        with self.assertRaisesRegex(ClassificationFailure, "retries exhausted"):
            ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(recipe, review)
        self.assertEqual(len(provider.calls), 3)

    def test_hard_provider_failure_is_not_retried(self):
        provider = Provider([PermissionError("denied")])
        with self.assertRaisesRegex(ClassificationFailure, "non-retryable"):
            ReviewClassifier(provider, "offline", sleep=lambda _: None).classify(RECIPE, REVIEW)
        self.assertEqual(len(provider.calls), 1)

    def test_highest_voted_skip_falls_back_to_next_ranked_proposal(self):
        primary = {"text": "Praise", "rating": 5, "reviewer": "A", "helpful_votes": 8, "date": "2026-01-01"}
        featured = [{"text": "Also praise", "rating": 5, "reviewer": "B", "helpful_votes": 10}]
        logs = __import__("io").StringIO()
        sink = logger.add(logs, format="{message}")
        try:
            result, calls = self.run_pipeline_for_pool(primary, featured, outcome=["skip", "proposal"])
        finally:
            logger.remove(sink)
        self.assertEqual(result["status"], "proposal")
        self.assertEqual([review["id"] for review in calls], ["review-featured-0001", "review-primary-0001"])
        self.assertEqual(result["selected_review"]["id"], "review-primary-0001")
        self.assertEqual(result["skipped_reviews"], [{
            "review_id": "review-featured-0001", "source": "featured",
            "reason": "Model skip reason for review-featured-0001",
        }])
        self.assertIn("considering candidate review=review-featured-0001 source=featured reviewer=B rating=5 helpful_votes=10", logs.getvalue())
        self.assertIn("review=review-featured-0001 source=featured reviewer=B rating=5 helpful_votes=10 date=unknown: semantic skip", logs.getvalue())

    def test_all_candidates_skipped_preserves_first_selected_review_and_trace(self):
        primary = {"text": "primary", "rating": 5, "helpful_votes": 8}
        featured = [{"text": "featured", "rating": 5, "helpful_votes": 10}]
        result, calls = self.run_pipeline_for_pool(primary, featured)
        self.assertEqual(result["status"], "exhausted")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["selected_review"]["id"], "review-featured-0001")
        self.assertEqual([row["review_id"] for row in result["skipped_reviews"]], [
            "review-featured-0001", "review-primary-0001",
        ])
        self.assertEqual([row["reason"] for row in result["skipped_reviews"]], [
            "Model skip reason for review-featured-0001", "Model skip reason for review-primary-0001",
        ])

    def test_tie_preserves_normalized_order(self):
        primary = {"text": "primary", "rating": 5, "helpful_votes": 10}
        featured = [{"text": "featured", "rating": 5, "helpful_votes": 10}]
        result, calls = self.run_pipeline_for_pool(primary, featured)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["selected_review"]["id"], "review-primary-0001")

    def test_single_candidate_skip_keeps_selected_review_and_reason(self):
        primary = {"text": "only review", "rating": 5, "helpful_votes": 10}
        result, calls = self.run_pipeline_for_pool(primary)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "exhausted")
        self.assertEqual(result["selected_review"]["id"], "review-primary-0001")
        self.assertEqual(result["skipped_reviews"], [{
            "review_id": "review-primary-0001", "source": "primary",
            "reason": "Model skip reason for review-primary-0001",
        }])

    def test_known_count_ranks_ahead_of_unknown_count(self):
        primary = {"text": "primary", "rating": 5, "helpful_votes": None}
        featured = [{"text": "featured", "rating": 5, "helpful_votes": 0}]
        result, calls = self.run_pipeline_for_pool(primary, featured)
        self.assertEqual(calls[0]["source"], "featured")
        self.assertEqual(result["selected_review"]["helpful_votes"], 0)

    def test_all_unknown_counts_keep_normalized_order(self):
        primary = {"text": "primary", "rating": 5}
        featured = [{"text": "featured first", "rating": 5}, {"text": "featured second", "rating": 5}]
        result, calls = self.run_pipeline_for_pool(primary, featured)
        self.assertEqual(calls[0]["id"], "review-primary-0001")
        self.assertEqual(result["selected_review"]["helpful_votes"], None)

    def test_empty_candidate_pool_is_exhausted_without_selection(self):
        result, calls = self.run_pipeline_for_pool()
        self.assertEqual(result["status"], "exhausted")
        self.assertIsNone(result["selected_review"])
        self.assertEqual(calls, [])

    def test_provider_failure_only_fails_for_selected_candidate(self):
        primary = {"text": "primary", "rating": 5, "helpful_votes": 2}
        featured = [{"text": "winner", "rating": 5, "helpful_votes": 10}]
        result, calls = self.run_pipeline_for_pool(primary, featured, outcome="failure")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["selected_review"]["id"], "review-featured-0001")
        self.assertEqual(result["skipped_reviews"], [])

    def test_provider_failure_after_skip_stops_with_failed_status(self):
        primary = {"text": "primary", "rating": 5, "helpful_votes": 2}
        featured = [{"text": "winner", "rating": 5, "helpful_votes": 10}]
        result, calls = self.run_pipeline_for_pool(primary, featured, outcome=["skip", "failure"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual([review["id"] for review in calls], ["review-featured-0001", "review-primary-0001"])
        self.assertEqual(result["selected_review"]["id"], "review-primary-0001")
        self.assertEqual(result["skipped_reviews"][0]["review_id"], "review-featured-0001")

    def test_proposal_result_has_normalized_selected_review_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "recipe.json"
            path.write_text(json.dumps({"recipe_id": "r", "ingredients": [], "instructions": [],
                "most_helpful_positive_review": {"text": "I chilled it.", "rating": 5, "reviewer": "A", "helpful_votes": 8, "date": "2026-01-01", "permalink": "https://example.invalid/review"}}), encoding="utf-8")
            pipeline = LLMAnalysisPipeline.__new__(LLMAnalysisPipeline)
            proposal = {"review_id": "review-primary-0001", "decision": "propose", "modifications": []}
            classified = SimpleNamespace(decision="propose", modifications=[object()], model_dump=lambda mode: proposal)
            pipeline.tweak_extractor = SimpleNamespace(classifier=SimpleNamespace(classify=lambda *args, **kwargs: classified))
            result = pipeline.classify_recipe_file(str(path))
            self.assertEqual(result["review_id"], "review-primary-0001")
            self.assertEqual(result["selected_review"], {
                "id": "review-primary-0001", "source": "primary", "reviewer": "A", "rating": 5,
                "helpful_votes": 8, "date": "2026-01-01", "permalink": "https://example.invalid/review"})

    def test_provider_failure_logs_review_identity_and_returns_failed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "recipe.json"
            path.write_text(json.dumps({"ingredients": [], "instructions": [],
                "most_helpful_positive_review": {"text": "Praise", "rating": 5, "reviewer": "A"}}), encoding="utf-8")
            pipeline = LLMAnalysisPipeline.__new__(LLMAnalysisPipeline)
            pipeline.tweak_extractor = SimpleNamespace(classifier=SimpleNamespace(
                classify=lambda *args, **kwargs: (_ for _ in ()).throw(ClassificationFailure("invalid response contract; retries exhausted"))))
            logs = __import__("io").StringIO()
            sink = logger.add(logs, format="{message}")
            try:
                result = pipeline.classify_recipe_file(str(path))
            finally:
                logger.remove(sink)
            self.assertEqual(result["status"], "failed")
            self.assertIn("review=review-primary-0001 source=primary reviewer=A", logs.getvalue())
            self.assertIn("provider/contract failure", logs.getvalue())

    def test_cli_writes_json_and_returns_failure_code(self):
        import test_pipeline
        with TemporaryDirectory() as directory:
            path = Path(directory) / "saved.json"
            path.write_text("{}", encoding="utf-8")
            class FakePipeline:
                def __init__(self): pass
                def classify_recipe_file(self, _):
                    return {"status": "failed", "failures": [{"review_id": "r", "error": "contract"}]}
            from contextlib import redirect_stderr, redirect_stdout
            from io import StringIO
            out = StringIO()
            with patch.object(test_pipeline, "LLMAnalysisPipeline", FakePipeline), \
                    patch.object(sys, "argv", ["test_pipeline.py", "stage3", str(path)]), \
                    redirect_stdout(out), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as result:
                    test_pipeline.main()
            self.assertEqual(result.exception.code, 1)
            self.assertEqual(json.loads(out.getvalue())["status"], "failed")

    def test_cli_logs_missing_input_path_without_stdout_json(self):
        import test_pipeline
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        missing = Path("missing-stage3-input.json").resolve()
        out, err = StringIO(), StringIO()
        sink = logger.add(err, format="{message}")
        try:
            with patch.object(sys, "argv", ["test_pipeline.py", "stage3", str(missing)]), \
                    redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit) as result:
                    test_pipeline.main()
        finally:
            logger.remove(sink)
        self.assertEqual(result.exception.code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn(str(missing), err.getvalue())


if __name__ == "__main__":
    unittest.main()
