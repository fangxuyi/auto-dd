"""Hallucination trap and basic contradiction tests for the LLM retry layer."""
import json

import pytest

from company_research.llm.retry import LLMStructuredOutputError, call_with_retry, parse_json_block
from company_research.models.evidence import EvidenceFact


def test_parse_json_block_plain():
    assert parse_json_block('{"a": 1}') == {"a": 1}


def test_parse_json_block_fenced():
    text = "```json\n[1, 2, 3]\n```"
    assert parse_json_block(text) == [1, 2, 3]


def test_parse_json_block_fenced_no_lang():
    text = "```\n{\"x\": true}\n```"
    assert parse_json_block(text) == {"x": True}


def test_call_with_retry_succeeds_first_try():
    def call(prompt: str) -> str:
        return '[{"a": 1}]'

    def repair(prev, err, schema):
        return "repair"

    result = call_with_retry(call, repair, "prompt", model_class=None, is_list=True)
    assert result == [{"a": 1}]


def test_call_with_retry_succeeds_on_second_attempt():
    calls = []

    def call(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "not json at all"
        return '[{"a": 1}]'

    def repair(prev, err, schema):
        return "repair"

    result = call_with_retry(call, repair, "prompt", model_class=None, is_list=True)
    assert result == [{"a": 1}]
    assert len(calls) == 2


def test_call_with_retry_fails_after_max():
    def call(prompt: str) -> str:
        return "still not json"

    def repair(prev, err, schema):
        return "repair"

    with pytest.raises(LLMStructuredOutputError):
        call_with_retry(call, repair, "prompt", model_class=None, is_list=True, max_retries=2)
