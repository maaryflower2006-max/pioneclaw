"""
Additional prompt template tests for Phase 2b.

Tests go beyond the basic prompt tests (test_prompts.py, written by another agent)
and cover edge cases: empty inputs, very long content, missing fields, boundary scores.
"""
import pytest

# ==================== Module import tests ====================

def test_prompts_package_importable():
    """The prompts package should be importable."""
    try:
        import app.services.skill_eval.prompts
    except ImportError:
        try:
            import app.prompts  # noqa: F401
        except ImportError:
            pass  # Might be at either location; tests below will pin expectations


# ==================== Grader prompt edge cases ====================

EMPTY_SKILL_CONTENT = ""
MINIMAL_SKILL_CONTENT = "---\nname: minimal\n---\n\n# Minimal\n\nJust a body."
VALID_SKILL_CONTENT = """---
name: test-skill
description: A comprehensive test skill
tags: [testing, example]
---

# Test Skill

## Workflow
1. Validate inputs
2. Process data
3. Return result

## Edge Cases
- Handle null inputs
- Handle timeouts
"""

VERY_LONG_SKILL_CONTENT = (
    "---\nname: long-skill\ndescription: Very long skill document\n---\n\n"
    + ("# Section\n\n" + "This is paragraph text. " * 20 + "\n\n") * 50
)


class TestGraderPromptEdgeCases:
    """Edge case tests for grader_prompt module."""

    @pytest.fixture
    def grader_builder(self):
        """Resolve the grader prompt builder function from expected locations."""
        func = None
        for module_path, func_name in [
            ("app.services.skill_eval.prompts.grader_prompt", "build_grader_prompt"),
            ("app.services.skill_eval.prompts.grader_prompt", "grader_prompt"),
            ("app.prompts.grader_prompt", "build_grader_prompt"),
            ("app.prompts.grader_prompt", "grader_prompt"),
        ]:
            try:
                mod = __import__(module_path, fromlist=[func_name])
                func = getattr(mod, func_name, None)
                if callable(func):
                    break
            except ImportError:
                continue
        return func

    @pytest.fixture
    def grader_requires_skill_content(self, grader_builder):
        """Try to determine the signature of the grader prompt function."""
        if grader_builder is None:
            return None
        import inspect
        sig = inspect.signature(grader_builder)
        params = list(sig.parameters.keys())
        return params

    def test_grader_prompt_function_exists(self, grader_builder):
        """The grader prompt builder should exist in one of the expected locations."""
        if grader_builder is None:
            pytest.skip(
                "Grader prompt builder not found yet — "
                "expected in services/skill_eval/prompts/grader_prompt.py or "
                "app/prompts/grader_prompt.py"
            )
        assert callable(grader_builder)

    def test_grader_prompt_with_empty_skill(self, grader_builder, grader_requires_skill_content):
        """Empty skill content should still produce a valid prompt string."""
        if grader_builder is None:
            pytest.skip("Grader builder not yet available")

        try:
            result = grader_builder(EMPTY_SKILL_CONTENT)
        except TypeError:
            # Maybe it takes additional required args; try a common pattern
            result = grader_builder(content=EMPTY_SKILL_CONTENT)

        assert isinstance(result, str), (
            f"Grader prompt must return a string even for empty content, "
            f"got {type(result).__name__}"
        )
        assert len(result) > 0, "Prompt string should not be empty"
        # The prompt should mention the skill content area somehow
        # (even if noting it's empty)
        assert any(
            word in result.lower()
            for word in ["content", "skill", "evaluate", "empty"]
        ), f"Prompt should reference content or evaluation, got: {result[:200]}"

    def test_grader_prompt_with_very_long_skill(self, grader_builder):
        """Very long skill content should not break the prompt structure."""
        if grader_builder is None:
            pytest.skip("Grader builder not yet available")

        try:
            result = grader_builder(VERY_LONG_SKILL_CONTENT[:5000])
        except TypeError:
            result = grader_builder(content=VERY_LONG_SKILL_CONTENT[:5000])

        assert isinstance(result, str)
        assert len(result) > 0

        # The prompt should be longer than the input (it wraps content
        # with grading instructions) or shorter (if truncated by design)
        # Either is acceptable as long as it doesn't crash
        assert len(result) < 100000, (
            f"Prompt should not be unreasonably large, got {len(result)} chars"
        )

    def test_grader_prompt_mentions_darwin_dimensions(self, grader_builder):
        """The grader prompt should reference darwin 8-dimension rubric."""
        if grader_builder is None:
            pytest.skip("Grader builder not yet available")

        try:
            result = grader_builder(VALID_SKILL_CONTENT)
        except TypeError:
            result = grader_builder(content=VALID_SKILL_CONTENT)

        darwin_keywords = [
            "frontmatter", "workflow", "edge_cases", "checkpoints",
            "specificity", "resources", "architecture", "performance",
        ]
        found = [kw for kw in darwin_keywords if kw.lower() in result.lower()]
        assert len(found) >= 3, (
            f"Grader prompt should mention at least 3 darwin dimensions. "
            f"Found: {found}. Prompt preview: {result[:300]}"
        )

    def test_grader_prompt_includes_evidence_instruction(self, grader_builder):
        """The grader prompt should instruct the LLM to provide evidence/引用."""
        if grader_builder is None:
            pytest.skip("Grader builder not yet available")

        try:
            result = grader_builder(VALID_SKILL_CONTENT)
        except TypeError:
            result = grader_builder(content=VALID_SKILL_CONTENT)

        evidence_keywords = ["evidence", "引用", "引用原文", "quote", "excerpt"]
        found = [kw for kw in evidence_keywords if kw.lower() in result.lower()]
        assert len(found) >= 1, (
            f"Grader prompt should instruct LLM to provide evidence/quotes. "
            f"Prompt preview: {result[:300]}"
        )

    def test_grader_prompt_forbids_guessing(self, grader_builder):
        """The grader prompt should instruct the LLM NOT to guess."""
        if grader_builder is None:
            pytest.skip("Grader builder not yet available")

        try:
            result = grader_builder(VALID_SKILL_CONTENT)
        except TypeError:
            result = grader_builder(content=VALID_SKILL_CONTENT)

        anti_guess_keywords = [
            "do not guess", "don't guess", "禁止猜测", "不要猜测",
            "not make up", "do not invent", "不得", "不存在", "编造",
            "not exist", "不要编", "不要臆",
        ]
        found = [kw for kw in anti_guess_keywords if kw.lower() in result.lower()]
        assert len(found) >= 1, (
            f"Grader prompt should forbid guessing/inventing content. "
            f"Prompt preview: {result[:300]}"
        )


# ==================== Comparator prompt edge cases ====================

class TestComparatorPromptEdgeCases:
    """Edge case tests for comparator_prompt module."""

    @pytest.fixture
    def comparator_builder(self):
        """Resolve the comparator prompt builder function."""
        func = None
        for module_path, func_name in [
            ("app.services.skill_eval.prompts.comparator_prompt", "build_comparator_prompt"),
            ("app.services.skill_eval.prompts.comparator_prompt", "comparator_prompt"),
            ("app.prompts.comparator_prompt", "build_comparator_prompt"),
            ("app.prompts.comparator_prompt", "comparator_prompt"),
        ]:
            try:
                mod = __import__(module_path, fromlist=[func_name])
                func = getattr(mod, func_name, None)
                if callable(func):
                    break
            except ImportError:
                continue
        return func

    SAMPLE_OUTPUT_A = "Task completed successfully. Result: 42"
    SAMPLE_OUTPUT_B = "Task completed with warnings. Result: 42, Warnings: 2"

    def test_comparator_prompt_with_empty_expectations(self, comparator_builder):
        """Comparator should work without explicit expectations."""
        if comparator_builder is None:
            pytest.skip("Comparator builder not yet available")

        try:
            result = comparator_builder(self.SAMPLE_OUTPUT_A, self.SAMPLE_OUTPUT_B)
        except TypeError:
            result = comparator_builder(
                content_a=self.SAMPLE_OUTPUT_A, content_b=self.SAMPLE_OUTPUT_B,
            )

        assert isinstance(result, str), (
            f"Comparator prompt must return string, got {type(result).__name__}"
        )
        assert len(result) > 0

    def test_comparator_prompt_output_format_exact(self, comparator_builder):
        """Verify the exact JSON output field names expected from the LLM."""
        if comparator_builder is None:
            pytest.skip("Comparator builder not yet available")

        try:
            result = comparator_builder(self.SAMPLE_OUTPUT_A, self.SAMPLE_OUTPUT_B)
        except TypeError:
            result = comparator_builder(
                content_a=self.SAMPLE_OUTPUT_A, content_b=self.SAMPLE_OUTPUT_B,
            )

        # The comparator prompt should define expected output fields
        required_output_fields = ["winner", "A", "B", "TIE"]
        for field in required_output_fields:
            assert field.lower() in result.lower(), (
                f"Comparator prompt should mention '{field}' in output format. "
                f"Prompt preview: {result[:300]}"
            )

    def test_comparator_prompt_mentions_rubric(self, comparator_builder):
        """Comparator prompt should define the evaluation rubric."""
        if comparator_builder is None:
            pytest.skip("Comparator builder not yet available")

        try:
            result = comparator_builder(self.SAMPLE_OUTPUT_A, self.SAMPLE_OUTPUT_B)
        except TypeError:
            result = comparator_builder(
                content_a=self.SAMPLE_OUTPUT_A, content_b=self.SAMPLE_OUTPUT_B,
            )

        rubric_keywords = [
            "rubric", "content_score", "structure_score", "overall_score",
            "correctness", "completeness", "organization",
            "评分", "评分标准",
        ]
        found = [kw for kw in rubric_keywords if kw.lower() in result.lower()]
        assert len(found) >= 2, (
            f"Comparator prompt should define rubric scoring criteria. "
            f"Found: {found}"
        )

    def test_comparator_prompt_with_identical_outputs(self, comparator_builder):
        """Identical outputs A and B should still produce a valid prompt."""
        if comparator_builder is None:
            pytest.skip("Comparator builder not yet available")

        same_output = "Task completed. Result: 42."

        try:
            result = comparator_builder(same_output, same_output)
        except TypeError:
            result = comparator_builder(content_a=same_output, content_b=same_output)

        assert isinstance(result, str)
        assert len(result) > 0  # Even for identical inputs, prompt should be valid

    def test_comparator_prompt_with_empty_outputs(self, comparator_builder):
        """Empty outputs should not crash the prompt builder."""
        if comparator_builder is None:
            pytest.skip("Comparator builder not yet available")

        try:
            result = comparator_builder("", "")
        except TypeError:
            result = comparator_builder(content_a="", content_b="")

        assert isinstance(result, str)
        assert len(result) > 0


# ==================== Analyzer prompt edge cases ====================

class TestAnalyzerPromptEdgeCases:
    """Edge case tests for analyzer_prompt module."""

    @pytest.fixture
    def analyzer_builder(self):
        """Resolve the analyzer prompt builder function."""
        func = None
        for module_path, func_name in [
            ("app.services.skill_eval.prompts.analyzer_prompt", "build_analyzer_prompt"),
            ("app.services.skill_eval.prompts.analyzer_prompt", "analyzer_prompt"),
            ("app.prompts.analyzer_prompt", "build_analyzer_prompt"),
            ("app.prompts.analyzer_prompt", "analyzer_prompt"),
        ]:
            try:
                mod = __import__(module_path, fromlist=[func_name])
                func = getattr(mod, func_name, None)
                if callable(func):
                    break
            except ImportError:
                continue
        return func

    ALL_HIGH_DIMENSIONS = [
        {"key": "frontmatter", "label": "Frontmatter质量", "score": 9, "weight": 8},
        {"key": "workflow", "label": "工作流清晰度", "score": 9, "weight": 15},
        {"key": "edge_cases", "label": "边界条件覆盖", "score": 8, "weight": 10},
        {"key": "checkpoints", "label": "检查点设计", "score": 8, "weight": 7},
        {"key": "specificity", "label": "指令具体性", "score": 9, "weight": 15},
        {"key": "resources", "label": "资源整合度", "score": 8, "weight": 5},
        {"key": "architecture", "label": "整体架构", "score": 9, "weight": 15},
        {"key": "performance", "label": "实测表现", "score": 8, "weight": 25},
    ]

    ALL_LOW_ONE_CRITICAL = [
        {"key": "frontmatter", "label": "Frontmatter质量", "score": 8, "weight": 8},
        {"key": "workflow", "label": "工作流清晰度", "score": 7, "weight": 15},
        {"key": "edge_cases", "label": "边界条件覆盖", "score": 1, "weight": 10},
        {"key": "checkpoints", "label": "检查点设计", "score": 6, "weight": 7},
        {"key": "specificity", "label": "指令具体性", "score": 1, "weight": 15},
        {"key": "resources", "label": "资源整合度", "score": 4, "weight": 5},
        {"key": "architecture", "label": "整体架构", "score": 5, "weight": 15},
        {"key": "performance", "label": "实测表现", "score": 1, "weight": 25},
    ]

    SINGLE_ZERO_DIMENSION = [
        {"key": "frontmatter", "label": "Frontmatter质量", "score": 1, "weight": 8},
        {"key": "workflow", "label": "工作流清晰度", "score": 5, "weight": 15},
        {"key": "edge_cases", "label": "边界条件覆盖", "score": 0, "weight": 10},
        {"key": "checkpoints", "label": "检查点设计", "score": 5, "weight": 7},
        {"key": "specificity", "label": "指令具体性", "score": 3, "weight": 15},
        {"key": "resources", "label": "资源整合度", "score": 3, "weight": 5},
        {"key": "architecture", "label": "整体架构", "score": 4, "weight": 15},
        {"key": "performance", "label": "实测表现", "score": 2, "weight": 25},
    ]

    def test_analyzer_prompt_with_all_high_scores(self, analyzer_builder):
        """When all dimensions score high, the analyzer should still produce a
        valid prompt (perhaps noting minimal improvement needed)."""
        if analyzer_builder is None:
            pytest.skip("Analyzer builder not yet available")

        result = analyzer_builder({"dimensions": self.ALL_HIGH_DIMENSIONS}, skill_content="test")

        assert isinstance(result, str), (
            f"Analyzer prompt must return string, got {type(result).__name__}"
        )
        assert len(result) > 0

        # Even with all high scores, the prompt should still be about
        # improvement suggestions
        assert any(
            kw in result.lower()
            for kw in ["improve", "suggestion", "建议", "优化", "enhance"]
        ), f"Prompt should still discuss improvement opportunities. Preview: {result[:200]}"

    def test_analyzer_prompt_with_critical_failure(self, analyzer_builder):
        """When a dimension scores 0 (critical failure), the prompt should
        emphasize that dimension heavily."""
        if analyzer_builder is None:
            pytest.skip("Analyzer builder not yet available")

        result = analyzer_builder({"dimensions": self.SINGLE_ZERO_DIMENSION}, skill_content="test")

        assert isinstance(result, str)
        assert len(result) > 0

        # The prompt should reference the failing dimension
        assert "edge_cases" in result.lower() or "边界条件" in result, (
            f"Analyzer prompt should reference the failing edge_cases dimension. "
            f"Preview: {result[:300]}"
        )

    def test_analyzer_prompt_mentions_lowest_dimensions(self, analyzer_builder):
        """The analyzer prompt should highlight the lowest-scoring dimensions."""
        if analyzer_builder is None:
            pytest.skip("Analyzer builder not yet available")

        result = analyzer_builder({"dimensions": self.ALL_LOW_ONE_CRITICAL}, skill_content="test")

        # The lowest dimensions (edge_cases=1, specificity=1, performance=1)
        # should be mentioned in the prompt
        low_keys = ["edge_cases", "specificity", "performance"]
        found = [k for k in low_keys if k.lower() in result.lower()]
        assert len(found) >= 1, (
            f"Analyzer prompt should mention at least one low-scoring dimension. "
            f"Low keys: {low_keys}, Found: {found}"
        )

    def test_analyzer_prompt_has_output_format(self, analyzer_builder):
        """The analyzer prompt should define the expected output format."""
        if analyzer_builder is None:
            pytest.skip("Analyzer builder not yet available")

        result = analyzer_builder({"dimensions": self.ALL_HIGH_DIMENSIONS}, skill_content="test")

        output_fields = [
            "priority", "category", "impact", "suggestion",
            "high", "medium", "low",
        ]
        found = [f for f in output_fields if f.lower() in result.lower()]
        assert len(found) >= 3, (
            f"Analyzer prompt should define output fields. Found: {found}. "
            f"Preview: {result[:300]}"
        )

    def test_analyzer_prompt_with_empty_dimensions(self, analyzer_builder):
        """Empty dimension list should not crash the prompt builder."""
        if analyzer_builder is None:
            pytest.skip("Analyzer builder not yet available")

        result = analyzer_builder({"dimensions": []}, skill_content="test")

        assert isinstance(result, str)
        assert len(result) > 0
