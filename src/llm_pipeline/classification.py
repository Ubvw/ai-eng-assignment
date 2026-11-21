"""Typed Stage 3 review classification boundary."""

import json
import re
import time
from pathlib import Path
from typing import Annotated, Literal, Union

from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuantityChange(StrictModel):
    mode: Literal["add", "subtract", "multiply"]
    amount: str | None = None
    unit: str | None = None
    factor: str | None = None

    @model_validator(mode="after")
    def valid_form(self):
        if self.mode == "multiply":
            if self.factor is None or self.amount is not None or self.unit is not None:
                raise ValueError("multiply requires factor only")
        elif self.amount is None or self.unit is None or self.factor is not None:
            raise ValueError("add/subtract require amount and unit only")
        return self


class ReplaceEdit(StrictModel):
    operation: Literal["replace"]
    target_id: str
    replacement_text: str = Field(min_length=1)
    quantity_change: QuantityChange | None = None


class RemoveEdit(StrictModel):
    operation: Literal["remove"]
    target_id: str


class InsertEdit(StrictModel):
    operation: Literal["insert"]
    anchor_id: str
    position: Literal["before", "after"]
    text: str = Field(min_length=1)


Edit = Annotated[Union[ReplaceEdit, RemoveEdit, InsertEdit], Field(discriminator="operation")]


class Benefit(StrictModel):
    basis: Literal["reported", "inferred"]
    description: str = Field(min_length=1)


class Modification(StrictModel):
    id: str
    evidence_quotes: list[str] = Field(min_length=1)
    benefit: Benefit
    edits: list[Edit] = Field(min_length=1)


class SkipResult(StrictModel):
    review_id: str
    decision: Literal["skip"]
    reason: str


class ProposeResult(StrictModel):
    review_id: str
    decision: Literal["propose"]
    modifications: list[Modification] = Field(min_length=1)


Classification = Annotated[Union[SkipResult, ProposeResult], Field(discriminator="decision")]


class ClassificationFailure(RuntimeError):
    """Exhausted provider or response-contract failure, distinct from a semantic skip."""


class ResponseContractError(ValueError):
    pass


def approved_messages() -> list[dict[str, str]]:
    """Load the approved prompt and its 21 compact user/assistant example pairs."""
    path = Path(__file__).resolve().parents[2] / ".scratch/recipe-enhancement-pipeline/stage-3-system-prompt.md"
    source = path.read_text(encoding="utf-8")
    system = re.search(r"## System message\s+```text\s*(.*?)\s*```", source, re.S)
    if not system:
        raise RuntimeError(f"Approved Stage 3 system rules missing from {path}")
    examples = re.findall(r"```json\s*(.*?)\s*```", source, re.S)
    if len(examples) != 42:
        raise RuntimeError(f"Expected 21 approved JSON example pairs, found {len(examples) // 2}")
    messages = [{"role": "system", "content": system.group(1)}]
    for index in range(0, len(examples), 2):
        messages.extend((
            {"role": "user", "content": json.dumps(json.loads(examples[index]), separators=(",", ":"), ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(json.loads(examples[index + 1]), separators=(",", ":"), ensure_ascii=False)},
        ))
    return messages


class ReviewClassifier:
    def __init__(self, client, model: str, retries: int = 2, sleep=time.sleep):
        self.client = client
        self.model = model
        self.retries = retries
        self.sleep = sleep

    def classify(self, recipe: dict, review: dict, on_retry=lambda attempt, reason: None) -> Classification:
        messages = approved_messages()
        messages.append({"role": "user", "content": json.dumps({"recipe": recipe, "review": review}, separators=(",", ":"), ensure_ascii=False)})
        for attempt in range(self.retries + 1):
            failure = None
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages, response_format={"type": "json_object"},
                    temperature=0.1, max_tokens=16384,
                )
                try:
                    raw = response.choices[0].message.content
                except (AttributeError, IndexError, TypeError) as exc:
                    raise ResponseContractError("response had no message content") from exc
                if not raw:
                    raise ResponseContractError("empty response")
                result = TypeAdapter(Classification).validate_json(raw)
                if result.review_id != review["id"]:
                    raise ResponseContractError("response review_id did not match candidate")
                if result.decision == "propose" and any(
                    quote not in review["text"] for mod in result.modifications for quote in mod.evidence_quotes
                ):
                    raise ResponseContractError("evidence quote was not found verbatim in candidate review")
                if result.decision == "propose":
                    recipe_ids = {
                        item["id"]
                        for section in ("ingredients", "instructions")
                        for item in recipe.get(section, [])
                    }
                    for mod in result.modifications:
                        for edit in mod.edits:
                            referenced_id = edit.anchor_id if isinstance(edit, InsertEdit) else edit.target_id
                            if referenced_id not in recipe_ids:
                                raise ResponseContractError(
                                    f"edit reference {referenced_id!r} was not an exact recipe ID"
                                )
                return result
            except (json.JSONDecodeError, ValidationError, ResponseContractError) as exc:
                failure = exc
                retryable = True
                reason = "invalid response contract"
            except (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError) as exc:
                failure = exc
                retryable = True
                reason = type(exc).__name__
            except Exception as exc:
                raise ClassificationFailure(f"non-retryable provider failure: {type(exc).__name__}") from exc
            if not retryable or attempt >= self.retries:
                raise ClassificationFailure(f"{reason}; retries exhausted after {attempt + 1} attempt(s)") from failure
            on_retry(attempt + 1, reason)
            self.sleep(min(0.25 * (2 ** attempt), 1.0))
        raise AssertionError("unreachable")
