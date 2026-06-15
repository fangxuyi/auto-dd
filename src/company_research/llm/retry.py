from __future__ import annotations

import json
import logging
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMStructuredOutputError(Exception):
    pass


def parse_json_block(text: str) -> Any:
    """Extract and parse JSON from a response that may contain markdown fences."""
    import re
    # Try fenced code block first
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text, re.IGNORECASE)
    if m:
        text = m.group(1)
    return json.loads(text.strip())


def call_with_retry(
    call_fn: Callable[[str], str],
    repair_fn: Callable[[str, str, str], str],
    prompt: str,
    model_class: type[T] | None,
    is_list: bool = False,
    max_retries: int = 2,
) -> Any:
    """Call an LLM function with structured output, retrying on validation failure.

    Strategy:
    1. Call with original prompt.
    2. On validation error, retry with errors appended.
    3. On second failure, try repair prompt.
    4. If still invalid, raise LLMStructuredOutputError.
    """
    last_response = ""
    last_error = ""

    for attempt in range(max_retries + 1):
        if attempt == 0:
            current_prompt = prompt
        elif attempt == 1:
            current_prompt = (
                prompt
                + f"\n\nYour previous response had validation errors:\n{last_error}\n"
                "Please fix these errors and return only valid JSON."
            )
        else:
            current_prompt = repair_fn(last_response, last_error, str(model_class))

        last_response = call_fn(current_prompt)

        try:
            raw = parse_json_block(last_response)
            if model_class is None:
                return raw
            if is_list:
                return [model_class.model_validate(item) for item in raw]
            return model_class.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            last_error = str(e)
            log.warning("LLM output validation failed (attempt %d): %s", attempt + 1, last_error)

    raise LLMStructuredOutputError(
        f"LLM failed to produce valid structured output after {max_retries + 1} attempts. "
        f"Last error: {last_error}"
    )
