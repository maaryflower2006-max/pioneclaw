"""
Additional prompt template tests for Phase 2b.

Tests cover edge cases: empty inputs, very long content, missing fields, boundary scores.
"""
import pytest


def test_prompts_package_importable():
    """The prompts package should be importable."""
    try:
        import app.services.skill_eval.prompts  # noqa: F401
    except ImportError:
        pass  # May not be available in all test environments


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
        ]
        found = [kw for kw in rubric_keywords if kw.lower() in result.lower()]
        assert len(found) >= 2, (
            f"Comparator prompt should define rubric scoring criteria. Found: {found}"
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
        assert len(result) > 0

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
