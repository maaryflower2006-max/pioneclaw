"""
Test skill_optimizer.py — SkillOptimizer class.

Tests the optimize() method with mocked LLM provider.
"""
from unittest.mock import MagicMock

import pytest

from app.services.skill_eval.skill_optimizer import OptimizeRequest, SkillOptimizer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_suggestions():
    """Sample evaluation suggestions."""
    return [
        {"title": "Fix hardcoded paths", "detail": "Use env vars instead of C:\\Users\\Yue",
         "severity": "high", "category": "tools", "impact": "Other users cannot execute"},
        {"title": "Add edge case handling", "detail": "Include error handling for API failures",
         "severity": "high", "category": "instructions",
         "impact": "Skill fails silently on API error"},
        {"title": "Clarify workflow steps", "detail": "Add explicit input/output to each step",
         "severity": "medium", "category": "structure",
         "impact": "LLM may misinterpret vague steps"},
    ]


@pytest.fixture
def sample_content():
    """Sample SKILL.md content."""
    return """---
name: test-skill
description: A test skill for evaluation
---

## Workflow

Step 1: Do something
Step 2: Do something else

## Notes

This skill needs improvement.
"""


OPTIMIZED_CONTENT = """---
name: test-skill
description: A test skill for evaluation
---

## Workflow

Step 1: Validate input
Step 2: Execute main logic
Step 3: Check output

## Edge Cases

- If input is empty, return error message

## Notes

This skill needs improvement.
"""


def _make_async_gen(*items):
    """Helper to create an async generator from items."""
    async def gen():
        for item in items:
            yield item
    return gen()


@pytest.fixture
def mock_llm():
    """Mock SimpleLLMProvider returning optimized content."""
    llm = MagicMock()
    llm.chat_stream = MagicMock(return_value=_make_async_gen(
        {"content": OPTIMIZED_CONTENT, "finish_reason": "stop"}
    ))
    return llm


# ---------------------------------------------------------------------------
# Tests: optimize()
# ---------------------------------------------------------------------------


class TestOptimize:
    """Tests for SkillOptimizer.optimize()."""

    @pytest.mark.asyncio
    async def test_optimize_returns_string(self, mock_llm, sample_content, sample_suggestions):
        """optimize() should return a string (optimized SKILL.md content)."""
        optimizer = SkillOptimizer(provider=mock_llm)
        request = OptimizeRequest(content=sample_content, suggestions=sample_suggestions)
        result = await optimizer.optimize(request)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_optimize_calls_chat_stream(self, mock_llm, sample_content, sample_suggestions):
        """optimize() should call chat_stream on the provider."""
        optimizer = SkillOptimizer(provider=mock_llm)
        request = OptimizeRequest(content=sample_content, suggestions=sample_suggestions)
        await optimizer.optimize(request)

        mock_llm.chat_stream.assert_called()

    @pytest.mark.asyncio
    async def test_optimize_returns_improved_content(self, mock_llm, sample_content, sample_suggestions):
        """The returned content should be the optimized version from the LLM."""
        optimizer = SkillOptimizer(provider=mock_llm)
        request = OptimizeRequest(content=sample_content, suggestions=sample_suggestions)
        result = await optimizer.optimize(request)

        assert result.strip() == OPTIMIZED_CONTENT.strip()

    @pytest.mark.asyncio
    async def test_optimize_with_target_dimensions(self, mock_llm, sample_content, sample_suggestions):
        """optimize() should accept optional target_dimensions."""
        optimizer = SkillOptimizer(provider=mock_llm)
        request = OptimizeRequest(
            content=sample_content,
            suggestions=sample_suggestions,
            target_dimensions=["clarity", "trigger"],
        )
        result = await optimizer.optimize(request)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_optimize_with_benchmark_context(self, mock_llm, sample_content, sample_suggestions):
        """optimize() should accept optional benchmark_context."""
        optimizer = SkillOptimizer(provider=mock_llm)
        request = OptimizeRequest(
            content=sample_content,
            suggestions=sample_suggestions,
            benchmark_context={
                "assertion_summary": {"total": 5, "with_skill_passed": 4, "baseline_passed": 2},
                "stats": {"delta": {"time_seconds": "-5.0", "tokens": "+200"}},
                "runs": [{"prompt": "Test prompt", "with_pass": 2, "with_total": 3,
                          "baseline_pass": 1, "baseline_total": 3}],
            },
        )
        result = await optimizer.optimize(request)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_optimize_handles_empty_suggestions(self, mock_llm, sample_content):
        """optimize() should work with empty suggestions list."""
        optimizer = SkillOptimizer(provider=mock_llm)
        request = OptimizeRequest(content=sample_content, suggestions=[])
        result = await optimizer.optimize(request)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_optimize_strips_markdown_fences(self, sample_content, sample_suggestions):
        """Markdown fences in LLM output should be stripped."""
        fenced_content = f"```markdown\n{OPTIMIZED_CONTENT}\n```"

        llm = MagicMock()
        llm.chat_stream = MagicMock(return_value=_make_async_gen(
            {"content": fenced_content, "finish_reason": "stop"}
        ))

        optimizer = SkillOptimizer(provider=llm)
        request = OptimizeRequest(content=sample_content, suggestions=sample_suggestions)
        result = await optimizer.optimize(request)

        assert not result.startswith("```")
        assert result.strip() == OPTIMIZED_CONTENT.strip()

    @pytest.mark.asyncio
    async def test_optimize_handles_empty_response(self, sample_content, sample_suggestions):
        """Empty LLM response should return empty string."""
        llm = MagicMock()
        llm.chat_stream = MagicMock(return_value=_make_async_gen(
            {"content": "", "finish_reason": "stop"}
        ))

        optimizer = SkillOptimizer(provider=llm)
        request = OptimizeRequest(content=sample_content, suggestions=sample_suggestions)
        result = await optimizer.optimize(request)

        assert result == ""

    @pytest.mark.asyncio
    async def test_optimize_llm_error_raises(self, sample_content, sample_suggestions):
        """When LLM returns an error chunk, should raise RuntimeError."""
        llm = MagicMock()
        llm.chat_stream = MagicMock(return_value=_make_async_gen(
            {"error": "API error 500: Internal server error"}
        ))

        optimizer = SkillOptimizer(provider=llm)
        request = OptimizeRequest(content=sample_content, suggestions=sample_suggestions)

        with pytest.raises(RuntimeError):
            await optimizer.optimize(request)
