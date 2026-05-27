"""
Test prompt template builders for skill evaluation.

Tests the comparator prompt builder to verify it produces complete,
well-structured prompts with all required elements.
"""


class TestComparatorPrompt:
    """Test build_comparator_prompt() for blind A/B comparison."""

    def test_comparator_prompt_contains_rubric(self):
        """Verify Content+Structure rubric tables are present."""
        from app.services.skill_eval.prompts import build_comparator_prompt

        prompt = build_comparator_prompt("output A content", "output B content")
        # Content rubric criteria
        assert "correctness" in prompt.lower() or "正确性" in prompt, (
            "Comparator prompt must include correctness criterion"
        )
        assert "completeness" in prompt.lower() or "完整性" in prompt, (
            "Comparator prompt must include completeness criterion"
        )
        assert "accuracy" in prompt.lower() or "准确性" in prompt, (
            "Comparator prompt must include accuracy criterion"
        )
        # Structure rubric criteria
        assert "organization" in prompt.lower() or "组织" in prompt, (
            "Comparator prompt must include organization criterion"
        )
        assert "formatting" in prompt.lower() or "格式" in prompt, (
            "Comparator prompt must include formatting criterion"
        )
        assert "usability" in prompt.lower() or "可用性" in prompt, (
            "Comparator prompt must include usability criterion"
        )

    def test_comparator_prompt_contains_both_outputs(self):
        """Verify output A and output B are both present in the prompt."""
        from app.services.skill_eval.prompts import build_comparator_prompt

        output_a = "CONTENT_A: This is version A of the output."
        output_b = "CONTENT_B: This is version B of the output."
        prompt = build_comparator_prompt(output_a, output_b)
        assert output_a in prompt, "Comparator prompt must include output A content"
        assert output_b in prompt, "Comparator prompt must include output B content"

    def test_comparator_prompt_declares_winner(self):
        """Verify prompt instructs LLM to declare a winner."""
        from app.services.skill_eval.prompts import build_comparator_prompt

        prompt = build_comparator_prompt("a", "b")
        assert 'winner' in prompt.lower() or '胜者' in prompt or '胜出' in prompt, (
            "Comparator prompt must ask for a winner declaration"
        )
        assert 'A' in prompt and 'B' in prompt, (
            "Comparator prompt must reference labels A and B"
        )

    def test_comparator_prompt_accepts_eval_prompt(self):
        """Verify eval_prompt parameter is included when provided."""
        from app.services.skill_eval.prompts import build_comparator_prompt

        eval_prompt = "This is the original evaluation task description."
        prompt = build_comparator_prompt("out A", "out B", eval_prompt=eval_prompt)
        assert eval_prompt in prompt, (
            "Comparator prompt must include eval_prompt when provided"
        )

    def test_comparator_prompt_accepts_expectations(self):
        """Verify expectations list appears when provided."""
        from app.services.skill_eval.prompts import build_comparator_prompt

        expectations = ["Output must include name", "Output must be in JSON format"]
        prompt = build_comparator_prompt("out A", "out B", expectations=expectations)
        for exp in expectations:
            assert exp in prompt, (
                f"Expectation '{exp}' must appear in comparator prompt"
            )

    def test_comparator_prompt_asks_for_json_output(self):
        """Verify prompt asks for JSON output matching ComparisonResult."""
        from app.services.skill_eval.prompts import build_comparator_prompt

        prompt = build_comparator_prompt("a", "b")
        assert "JSON" in prompt, "Comparator prompt must require JSON output"
        assert "ComparisonResult" in prompt or "comparison" in prompt.lower(), (
            "Comparator prompt must reference ComparisonResult schema"
        )

    def test_comparator_prompt_contains_1_to_10_scale(self):
        """Verify prompt mentions the 1-10 overall scale."""
        from app.services.skill_eval.prompts import build_comparator_prompt

        prompt = build_comparator_prompt("a", "b")
        assert "1-10" in prompt or "1-5" in prompt or "1 到 10" in prompt or "1 到 5" in prompt, (
            "Comparator prompt must mention scoring scale"
        )


class TestAllExports:
    """Verify __init__.py exports the comparator builder."""

    def test_all_exports_contains_builders(self):
        """__all__ should list build_comparator_prompt."""
        from app.services.skill_eval.prompts import __all__ as exports

        assert "build_comparator_prompt" in exports
