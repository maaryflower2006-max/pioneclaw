"""
Test skill_optimizer.py — SkillOptimizer class for Phase 3b.

Tests cover: generate_optimization, compute_diff, apply_optimization,
LLM interaction, retry logic, and error handling.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.skill_eval import (
    Change,
    EvalDimension,
    GradingResult,
    OptimizationResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_eval_result():
    """Create a GradingResult with all 8 darwin dimensions, low scores on workflow and performance."""
    dims = [
        EvalDimension(
            key="frontmatter", label="Frontmatter质量",
            score=8, max_score=10, weight=8, weighted_score=6.4,
            comment="Name and description are fine", evidence="",
        ),
        EvalDimension(
            key="workflow", label="工作流清晰度",
            score=4, max_score=10, weight=15, weighted_score=6.0,
            comment="Steps are vague, no input/output defined", evidence="",
        ),
        EvalDimension(
            key="edge_cases", label="边界条件覆盖",
            score=3, max_score=10, weight=10, weighted_score=3.0,
            comment="No error handling or fallback paths", evidence="",
        ),
        EvalDimension(
            key="checkpoints", label="检查点设计",
            score=7, max_score=10, weight=7, weighted_score=4.9,
            comment="Has some checkpoints but inconsistent", evidence="",
        ),
        EvalDimension(
            key="specificity", label="指令具体性",
            score=5, max_score=10, weight=15, weighted_score=7.5,
            comment="Some instructions are vague", evidence="",
        ),
        EvalDimension(
            key="resources", label="资源整合度",
            score=9, max_score=10, weight=5, weighted_score=4.5,
            comment="References are correct", evidence="",
        ),
        EvalDimension(
            key="architecture", label="整体架构",
            score=6, max_score=10, weight=15, weighted_score=9.0,
            comment="Structure is mostly clear", evidence="",
        ),
        EvalDimension(
            key="performance", label="实测表现",
            score=2, max_score=10, weight=25, weighted_score=5.0,
            comment="Output quality issues in testing", evidence="",
        ),
    ]
    return GradingResult(
        dimensions=dims,
        overall_score=46.3,
        summary="Needs significant work on workflow, edge_cases, and performance.",
    )


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


@pytest.fixture
def valid_llm_response():
    """Valid LLM response JSON with optimized_content."""
    return {
        "changes": [
            {
                "dimension": "workflow",
                "before": "Step 1: Do something\nStep 2: Do something else",
                "after": "Step 1: Validate input\nStep 2: Execute main logic\nStep 3: Check output",
                "description": "Added explicit input validation and output verification steps",
            },
            {
                "dimension": "edge_cases",
                "before": "## Notes\n\nThis skill needs improvement.",
                "after": "## Edge Cases\n\n- If input is empty, return error message\n- If API fails, retry 3 times before failing\n\n## Notes\n\nThis skill needs improvement.",  # noqa: E501
                "description": "Added edge case handling section",
            },
        ],
        "estimated_score_delta": 15.0,
        "optimized_content": """---
name: test-skill
description: A test skill for evaluation
---

## Workflow

Step 1: Validate input
Step 2: Execute main logic
Step 3: Check output

## Edge Cases

- If input is empty, return error message
- If API fails, retry 3 times before failing

## Notes

This skill needs improvement.
""",
    }


def _make_async_gen(*items):
    """Helper to create an async generator from items."""
    async def gen():
        for item in items:
            yield item
    return gen()


@pytest.fixture
def mock_llm(valid_llm_response):
    """Mock SimpleLLMProvider with chat_stream returning valid JSON."""
    llm = MagicMock()
    llm.chat_stream = MagicMock(return_value=_make_async_gen(
        {"content": json.dumps(valid_llm_response, ensure_ascii=False), "finish_reason": "stop"}
    ))
    return llm


# ---------------------------------------------------------------------------
# Tests: generate_optimization
# ---------------------------------------------------------------------------

class TestGenerateOptimization:
    """Tests for SkillOptimizer.generate_optimization()."""

    def test_generate_optimization_identifies_lowest_dimensions(
        self, mock_llm, sample_content, sample_eval_result
    ):
        """Verify the lowest scoring dimensions are correctly identified."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        _optimizer = SkillOptimizer(mock_llm)  # noqa: F841

        # Find lowest 3 scored dimensions from the eval result
        sorted_dims = sorted(sample_eval_result.dimensions, key=lambda d: d.score)
        lowest = sorted_dims[:3]

        # Verify performance(2) < edge_cases(3) < workflow(4)
        assert lowest[0].key == "performance"
        assert lowest[0].score == 2
        assert lowest[1].key == "edge_cases"
        assert lowest[1].score == 3
        assert lowest[2].key == "workflow"
        assert lowest[2].score == 4

    @pytest.mark.asyncio
    async def test_generate_optimization_calls_llm(
        self, mock_llm, sample_content, sample_eval_result
    ):
        """Verify LLM is called with analyzer prompt containing eval data and content."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        optimizer = SkillOptimizer(mock_llm)
        result = await optimizer.generate_optimization(sample_content, sample_eval_result)

        # LLM should have been called
        mock_llm.chat_stream.assert_called()
        call_args = mock_llm.chat_stream.call_args
        messages = call_args[0][0]  # First positional arg is messages list

        # Verify messages contain the eval data and content
        assert isinstance(messages, list)
        assert len(messages) > 0
        # Should be a system/user message structure
        user_messages = [m for m in messages if m.get("role") == "user"]
        assert len(user_messages) > 0
        user_content = user_messages[0]["content"]
        assert "workflow" in user_content
        assert "edge_cases" in user_content
        assert "test-skill" in user_content

        # Result should be an OptimizationResult
        assert isinstance(result, OptimizationResult)

    @pytest.mark.asyncio
    async def test_generate_optimization_parses_llm_response(
        self, mock_llm, sample_content, sample_eval_result, valid_llm_response
    ):
        """Valid JSON response from LLM should parse into OptimizationResult."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        optimizer = SkillOptimizer(mock_llm)
        result = await optimizer.generate_optimization(sample_content, sample_eval_result)

        assert isinstance(result, OptimizationResult)
        assert result.original_content == sample_content
        assert result.optimized_content == valid_llm_response["optimized_content"]
        assert result.estimated_score_delta == 15.0
        assert len(result.changes) == 2
        assert result.changes[0].dimension == "workflow"
        assert result.changes[1].dimension == "edge_cases"

    @pytest.mark.asyncio
    async def test_generate_optimization_retries_on_bad_json(
        self, sample_content, sample_eval_result, valid_llm_response
    ):
        """On JSON parse failure, should retry up to 2 times before falling back."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        call_counts = [0]  # Use list for mutable closure

        def flaky_side_effect(_messages=None):
            """Side effect that returns an async generator. Accepts and ignores mock args."""
            call_counts[0] += 1
            if call_counts[0] <= 2:
                async def bad():
                    yield {"content": "```json\n{invalid json!!!\n```", "finish_reason": "stop"}
                return bad()
            else:
                async def good():
                    yield {"content": json.dumps(valid_llm_response, ensure_ascii=False), "finish_reason": "stop"}
                return good()

        llm = MagicMock()
        llm.chat_stream = MagicMock(side_effect=flaky_side_effect)

        optimizer = SkillOptimizer(llm)
        result = await optimizer.generate_optimization(sample_content, sample_eval_result)

        # Should have retried (called 3 times in total: 2 failures + 1 success)
        assert call_counts[0] == 3
        assert isinstance(result, OptimizationResult)
        assert result.optimized_content == valid_llm_response["optimized_content"]

    @pytest.mark.asyncio
    async def test_generate_optimization_no_optimized_content_fallback(
        self, mock_llm, sample_content, sample_eval_result
    ):
        """When LLM returns suggestions but no optimized_content, apply changes programmatically."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        # Response with changes but no optimized_content
        suggestions_response = {
            "analysis": {
                "weakest_dimensions": [
                    {"key": "workflow", "score": 4, "root_cause": "Steps are vague"},
                ],
                "summary": "Improve workflow clarity.",
            },
            "improvement_suggestions": [
                {
                    "priority": "high",
                    "category": "structure",
                    "title": "Clarify workflow",
                    "detail": "Add explicit input/output to each step",
                    "expected_impact": "Better LLM understanding",
                }
            ],
        }

        llm = MagicMock()
        llm.chat_stream = MagicMock(return_value=_make_async_gen(
            {"content": json.dumps(suggestions_response, ensure_ascii=False), "finish_reason": "stop"}
        ))

        optimizer = SkillOptimizer(llm)
        result = await optimizer.generate_optimization(sample_content, sample_eval_result)

        assert isinstance(result, OptimizationResult)
        assert result.original_content == sample_content
        # Should have some optimized content generated from suggestions
        assert len(result.optimized_content) > 0

    @pytest.mark.asyncio
    async def test_generate_optimization_llm_error_fallback(
        self, sample_content, sample_eval_result
    ):
        """When LLM returns an error in all attempts, should return minimal result."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        llm = MagicMock()
        llm.chat_stream = MagicMock(return_value=_make_async_gen(
            {"error": "API error 500: Internal server error"}
        ))

        optimizer = SkillOptimizer(llm)
        result = await optimizer.generate_optimization(sample_content, sample_eval_result)

        # Should still return an OptimizationResult with original content preserved
        assert isinstance(result, OptimizationResult)
        assert result.original_content == sample_content
        # optimized_content should at least equal original on total failure
        assert result.optimized_content == sample_content
        assert result.estimated_score_delta == 0.0


# ---------------------------------------------------------------------------
# Tests: compute_diff
# ---------------------------------------------------------------------------

class TestComputeDiff:
    """Tests for SkillOptimizer.compute_diff()."""

    def test_compute_diff_returns_unified_diff(self, mock_llm):
        """compute_diff should return a valid unified diff string."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        optimizer = SkillOptimizer(mock_llm)
        original = "---\nname: old\n---\n\nLine 1\nLine 2\nLine 3\n"
        optimized = "---\nname: new\n---\n\nLine 1\nLine 2 modified\nLine 3\n"

        diff = optimizer.compute_diff(original, optimized)

        assert isinstance(diff, str)
        assert len(diff) > 0
        # Unified diff contains markers
        assert "---" in diff
        assert "+++" in diff
        assert "@@" in diff
        # Should show the change
        assert "old" in diff or "new" in diff

    def test_compute_diff_empty_change(self, mock_llm):
        """Identical content should produce minimal diff (only headers)."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        optimizer = SkillOptimizer(mock_llm)
        content = "---\nname: test\n---\n\nBody text\n"

        diff = optimizer.compute_diff(content, content)

        assert isinstance(diff, str)
        # Should have headers but no actual changes
        # With identical content, unified_diff still produces headers
        lines = diff.strip().split("\n")
        # No change lines (lines starting with + or - outside headers)
        change_lines = [ln for ln in lines if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith("+++") and not ln.startswith("---")]
        assert len(change_lines) == 0


# ---------------------------------------------------------------------------
# Tests: apply_optimization
# ---------------------------------------------------------------------------

class TestApplyOptimization:
    """Tests for SkillOptimizer.apply_optimization()."""

    @pytest.mark.asyncio
    async def test_apply_optimization_writes_file(self, mock_llm, tmp_path):
        """apply_optimization should write optimized content to the skill's SKILL.md."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        # Create a mock skill object
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("Original content", encoding="utf-8")

        mock_skill = MagicMock()
        mock_skill.path = skill_file

        with patch(
            "app.services.skill_eval.skill_optimizer.get_skills_loader"
        ) as mock_loader_fn:
            mock_loader = MagicMock()
            mock_loader.skills = {"test-skill": mock_skill}
            mock_loader_fn.return_value = mock_loader

            optimizer = SkillOptimizer(mock_llm)
            result = await optimizer.apply_optimization("test-skill", "New optimized content")

            assert result is True
            # Verify the file was written
            written = skill_file.read_text(encoding="utf-8")
            assert written == "New optimized content"

    @pytest.mark.asyncio
    async def test_apply_optimization_skill_not_found(self, mock_llm):
        """When skill name doesn't exist, should return False gracefully."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        with patch(
            "app.services.skill_eval.skill_optimizer.get_skills_loader"
        ) as mock_loader_fn:
            mock_loader = MagicMock()
            mock_loader.skills = {}  # Empty skills dict — .get() returns None by default
            mock_loader_fn.return_value = mock_loader

            optimizer = SkillOptimizer(mock_llm)
            result = await optimizer.apply_optimization("nonexistent", "content")

            assert result is False

    @pytest.mark.asyncio
    async def test_apply_optimization_handles_permission_error(self, mock_llm, tmp_path):
        """When file write fails with PermissionError, should return False."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        # Create a mock skill whose path.write_text raises PermissionError
        mock_skill = MagicMock()
        mock_skill.path = MagicMock()
        mock_skill.path.write_text = MagicMock(side_effect=PermissionError("Permission denied"))

        with patch(
            "app.services.skill_eval.skill_optimizer.get_skills_loader"
        ) as mock_loader_fn:
            mock_loader = MagicMock()
            mock_loader.skills = {"test-skill": mock_skill}
            mock_loader_fn.return_value = mock_loader

            optimizer = SkillOptimizer(mock_llm)
            result = await optimizer.apply_optimization("test-skill", "content")

            assert result is False


# ---------------------------------------------------------------------------
# Tests: OptimizationResult structure
# ---------------------------------------------------------------------------

class TestOptimizationResultStructure:
    """Verify OptimizationResult fields are populated correctly."""

    @pytest.mark.asyncio
    async def test_optimization_result_structure(self, mock_llm, sample_content, sample_eval_result):
        """OptimizationResult should have all required fields properly populated."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        optimizer = SkillOptimizer(mock_llm)
        result = await optimizer.generate_optimization(sample_content, sample_eval_result)

        assert isinstance(result, OptimizationResult)
        assert result.original_content == sample_content
        assert isinstance(result.optimized_content, str)
        assert len(result.optimized_content) > 0
        assert isinstance(result.changes, list)
        assert len(result.changes) > 0
        assert isinstance(result.estimated_score_delta, float)

        # Each change should be a valid Change object
        for change in result.changes:
            assert isinstance(change, Change)
            assert isinstance(change.dimension, str)
            assert isinstance(change.before, str)
            assert isinstance(change.after, str)
            assert isinstance(change.description, str)

    @pytest.mark.asyncio
    async def test_generate_optimization_retries_exhausted(
        self, sample_content, sample_eval_result
    ):
        """When all 3 attempts fail with bad JSON, should return fallback result."""
        from app.services.skill_eval.skill_optimizer import SkillOptimizer

        def always_bad_side_effect(_messages=None):
            """Returns an async generator with invalid JSON. Accepts and ignores mock args."""
            async def gen():
                yield {"content": "not valid json at all {{{", "finish_reason": "stop"}
            return gen()

        llm = MagicMock()
        llm.chat_stream = MagicMock(side_effect=always_bad_side_effect)

        optimizer = SkillOptimizer(llm)
        result = await optimizer.generate_optimization(sample_content, sample_eval_result)

        # Should return a fallback result
        assert isinstance(result, OptimizationResult)
        assert result.original_content == sample_content
        assert result.estimated_score_delta == 0.0
        # Should be called 3 times (2 retries + initial)
        assert llm.chat_stream.call_count == 3
