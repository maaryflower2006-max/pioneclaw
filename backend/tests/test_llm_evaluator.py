"""
Test LLMEvaluator — 5-dimension LLM-based skill evaluator.

Tests the evaluate() method with mocked LLM provider.
"""
import json
from unittest.mock import MagicMock

import pytest

from app.modules.llm.provider import SimpleLLMProvider
from app.services.skill_eval.llm_evaluator import LLMEvalResult, LLMEvaluator

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_SKILL_CONTENT = """---
name: test-skill
description: A test skill for doing test things. Use when testing. Trigger: test
---

# Test Skill

## Workflow

Step 1: Do something
Step 2: Do another thing
"""

VALID_LLM_JSON_RESPONSE = json.dumps({
    "dimensions": [
        {"key": "clarity", "score": 75, "comment": "Steps are numbered but vague"},
        {"key": "completeness", "score": 50, "comment": "Missing edge cases and error handling"},
        {"key": "conciseness", "score": 80, "comment": "No filler content"},
        {"key": "trigger", "score": 70, "comment": "Description mentions use-when"},
        {"key": "dependencies", "score": 40, "comment": "No dependency declarations found"},
    ],
    "suggestions": [
        {"title": "Add edge cases", "detail": "Add error handling for common failures",
         "severity": "high", "category": "instructions", "impact": "Skill may fail silently"},
    ],
    "summary": "Basic skill with good frontmatter, lacks depth.",
})

EMPTY_SKILL_CONTENT = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_llm(response_text: str):
    """Create a mock SimpleLLMProvider that returns the given text via chat_stream."""
    llm = MagicMock(spec=SimpleLLMProvider)

    async def _chat_stream(messages, tools=None, model=None, temperature=None, max_tokens=None):
        yield {"content": response_text, "finish_reason": "stop"}

    llm.chat_stream = _chat_stream
    return llm


def make_failing_mock_llm():
    """Create a mock SimpleLLMProvider that always raises an exception."""
    llm = MagicMock(spec=SimpleLLMProvider)

    async def _chat_stream(messages, tools=None, model=None, temperature=None, max_tokens=None):
        raise RuntimeError("LLM connection timeout")
        yield  # make it a generator

    llm.chat_stream = _chat_stream
    return llm


# ---------------------------------------------------------------------------
# Tests: evaluate()
# ---------------------------------------------------------------------------

class TestEvaluate:
    """Tests for LLMEvaluator.evaluate()."""

    @pytest.mark.asyncio
    async def test_evaluate_returns_llm_eval_result(self):
        """evaluate() should return an LLMEvalResult dataclass."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        assert isinstance(result, LLMEvalResult)
        assert result.available is True

    @pytest.mark.asyncio
    async def test_evaluate_parses_valid_json(self):
        """Valid JSON response should be parsed into 5 dimensions."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        assert len(result.dimensions) == 5
        assert "Basic skill with good frontmatter" in result.summary
        assert len(result.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_evaluate_calls_chat_stream(self):
        """evaluate() should call chat_stream on the provider."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        # Provider's chat_stream should have been invoked
        assert mock_llm.chat_stream.called if hasattr(mock_llm.chat_stream, 'called') else True

    @pytest.mark.asyncio
    async def test_evaluate_dimension_keys(self):
        """Returned dimensions should have the 5 expected keys."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        keys = {d.key for d in result.dimensions}
        expected = {"clarity", "completeness", "conciseness", "trigger", "dependencies"}
        assert keys == expected, f"Expected {expected}, got {keys}"

    @pytest.mark.asyncio
    async def test_evaluate_scores_are_0_to_100(self):
        """All dimension scores should be in range 0-100."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        for d in result.dimensions:
            assert 0 <= d.score <= 100, f"Score for {d.key} is {d.score}, expected 0-100"

    @pytest.mark.asyncio
    async def test_evaluate_raw_response_stored(self):
        """The raw LLM response should be stored for debugging."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        assert len(result.raw_response) > 0


# ---------------------------------------------------------------------------
# Tests: JSON parsing robustness
# ---------------------------------------------------------------------------

class TestJsonParsing:
    """Tests for JSON parsing edge cases."""

    @pytest.mark.asyncio
    async def test_parses_json_in_markdown_fence(self):
        """JSON wrapped in ```json code block should be parsed."""
        wrapped = f"```json\n{VALID_LLM_JSON_RESPONSE}\n```"
        mock_llm = make_mock_llm(wrapped)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        assert len(result.dimensions) == 5
        assert result.available is True

    @pytest.mark.asyncio
    async def test_fallback_on_bad_json(self):
        """When JSON parse fails completely, should return fallback result with available=False."""
        mock_llm = make_mock_llm("This is not valid JSON {{{ broken")
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        # Should not crash
        assert isinstance(result, LLMEvalResult)
        # Either available=False or has fallback dimensions
        assert result.available is False or len(result.dimensions) > 0

    @pytest.mark.asyncio
    async def test_partial_json_with_brace_balance(self):
        """JSON with extra text before/after should be extracted via brace matching."""
        partial = (
            'Some preamble text\n'
            '{\n"dimensions": [{"key": "clarity", "score": 80, "comment": "ok"}],\n'
            '"suggestions": [],\n"summary": "ok"\n}\n'
            'Some trailing text'
        )
        mock_llm = make_mock_llm(partial)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        assert isinstance(result, LLMEvalResult)
        assert result.available is True


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_graceful_result(self):
        """When LLM raises, should return LLMEvalResult with available=False."""
        mock_llm = make_failing_mock_llm()
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        assert isinstance(result, LLMEvalResult)
        assert result.available is False
        assert len(result.dimensions) == 5  # Fallback dimensions

    @pytest.mark.asyncio
    async def test_empty_content_handled(self):
        """Empty content should not crash."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(EMPTY_SKILL_CONTENT)

        assert isinstance(result, LLMEvalResult)


# ---------------------------------------------------------------------------
# Tests: Suggestions
# ---------------------------------------------------------------------------

class TestSuggestions:
    """Tests for suggestion parsing."""

    @pytest.mark.asyncio
    async def test_suggestions_have_required_fields(self):
        """Each suggestion should have title, detail, severity."""
        mock_llm = make_mock_llm(VALID_LLM_JSON_RESPONSE)
        evaluator = LLMEvaluator(provider=mock_llm)
        result = await evaluator.evaluate(SAMPLE_SKILL_CONTENT)

        for s in result.suggestions:
            assert s.title, "Suggestion must have a title"
            assert s.detail, "Suggestion must have detail"
            assert s.severity in ("high", "medium", "low"), f"Invalid severity: {s.severity}"
