"""Ask-the-user tool helpers.

The ``ask_user`` tool lets the agent pause a run and put one or more questions to
the user, then resume with their answers. The actual pause/resume lives in the
WebSocket session (it owns the socket); this module just defines the question
schema and formats the collected answers into a result for the model.
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

MAX_QUESTIONS = 10


class QuestionItem(BaseModel):
    """One question to put to the user."""

    question: str = Field(description="The question text.")
    options: list[str] = Field(
        default_factory=list,
        description="Optional suggested answers, shown as numbered choices.",
    )
    allow_custom: bool = Field(
        default=True,
        description="Whether the user may type a free-form answer instead of picking an option.",
    )

    @field_validator("question", mode="before")
    @classmethod
    def _coerce_question(cls, v: Any) -> str:
        # Some providers return the question wrapped in a JSON string or list.
        if isinstance(v, (list, dict)):
            return json.dumps(v)
        return str(v)

    @field_validator("options", mode="before")
    @classmethod
    def _coerce_options(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            # Tolerate JSON-encoded strings: '["a","b"]' or "a,b"
            v_stripped = v.strip()
            if v_stripped.startswith("["):
                try:
                    parsed = json.loads(v_stripped)
                    if isinstance(parsed, list):
                        return [str(x) for x in parsed]
                except json.JSONDecodeError:
                    pass
            return [s for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]


def _coerce_questions(raw: Any) -> list[dict[str, Any]]:
    """Best-effort coercion of the `questions` argument into a list of dicts.

    Pydantic-ai forwards the model's tool-call args as-is. Some OpenAI-compatible
    providers serialize arrays as a JSON string with leading whitespace, e.g.
    `'\\n[{"question": "..."}]'`, which fails Pydantic's list-type validation
    with `Input should be a valid array`. This helper parses such strings
    before we hand them to QuestionItem.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            # Not JSON — treat as a single question text.
            return [{"question": raw}]
        raw = parsed
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return [{"question": str(raw)}]
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            try:
                item = json.loads(item.strip())
            except json.JSONDecodeError:
                item = {"question": item}
        if isinstance(item, dict):
            out.append(item)
        else:
            out.append({"question": str(item)})
    return out


def parse_questions(raw: Any) -> list[QuestionItem]:
    """Parse + validate the model's `questions` arg into QuestionItem objects.

    Returns at most MAX_QUESTIONS items. Any item that still fails validation
    after coercion is dropped (we'd rather ask fewer questions than crash the
    whole agent turn).
    """
    coerced = _coerce_questions(raw)[:MAX_QUESTIONS]
    items: list[QuestionItem] = []
    for c in coerced:
        try:
            items.append(QuestionItem.model_validate(c))
        except ValidationError:
            logger.warning("Dropping invalid question item: %r", c)
    return items


def format_answers(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> str:
    """Render the collected answers as a readable Q/A transcript for the model."""
    lines: list[str] = []
    for i, q in enumerate(questions):
        a = answers[i] if i < len(answers) else {}
        if not isinstance(a, dict):
            a = {}
        ans = "(skipped)" if a.get("skipped") else str(a.get("answer", "")).strip() or "(no answer)"
        lines.append(f"Q: {q.get('question', '')}\nA: {ans}")
    return "\n\n".join(lines)
