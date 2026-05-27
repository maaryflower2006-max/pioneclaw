"""
Test prompt template builders for skill evaluation.

Tests grader, comparator, and analyzer prompt builders to verify
they produce complete, well-structured prompts with all required elements.
"""


class TestGraderPrompt:
    """Test build_grader_prompt() for darwin-skill 8-dimension evaluation."""

    _8_DIMENSION_KEYS = [
        "frontmatter",
        "workflow",
        "edge_cases",
        "checkpoints",
        "specificity",
        "resources",
        "architecture",
        "performance",
    ]

    def test_grader_prompt_contains_all_8_dimensions(self):
        """Verify each of the 8 darwin-skill dimension keys appears in the prompt."""
        from app.services.skill_eval.prompts import build_grader_prompt

        prompt = build_grader_prompt("dummy content")
        for key in self._8_DIMENSION_KEYS:
            assert key in prompt, f"Dimension '{key}' not found in grader prompt"

    def test_grader_prompt_contains_skill_content(self):
        """Given skill content, it must appear in the output prompt."""
        from app.services.skill_eval.prompts import build_grader_prompt

        skill_content = "---\nname: test-skill\ndescription: A test skill\n---\n\nThis is test body."
        prompt = build_grader_prompt(skill_content)
        assert skill_content in prompt, (
            "Grader prompt must embed the skill content for LLM evaluation"
        )

    def test_grader_prompt_asks_for_json_output(self):
        """Verify JSON output instruction is present."""
        from app.services.skill_eval.prompts import build_grader_prompt

        prompt = build_grader_prompt("dummy")
        assert "JSON" in prompt, "Grader prompt must instruct LLM to output JSON"
        assert "GradingResult" in prompt or "grading" in prompt.lower(), (
            "Grader prompt must reference GradingResult schema"
        )

    def test_grader_prompt_contains_weights(self):
        """Verify prompts mention the weight values for each dimension."""
        from app.services.skill_eval.prompts import build_grader_prompt

        prompt = build_grader_prompt("dummy")
        # Check that weight references exist in the prompt
        for weight in ["8", "15", "10", "7", "5", "25"]:
            assert weight in prompt, f"Weight '{weight}' not found in grader prompt"

    def test_grader_prompt_contains_evidence_requirement(self):
        """Verify prompt asks to quote evidence from SKILL.md."""
        from app.services.skill_eval.prompts import build_grader_prompt

        prompt = build_grader_prompt("dummy")
        assert "证据" in prompt or "evidence" in prompt, (
            "Grader prompt must require evidence from SKILL.md"
        )


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


class TestAnalyzerPrompt:
    """Test build_analyzer_prompt() for optimization analysis."""

    _6_CATEGORIES = [
        "instructions",
        "tools",
        "examples",
        "error_handling",
        "structure",
        "references",
    ]

    def test_analyzer_prompt_contains_categories(self):
        """Verify all 6 analyzer categories are mentioned."""
        from app.services.skill_eval.prompts import build_analyzer_prompt

        eval_result = {
            "dimensions": [
                {"key": "frontmatter", "score": 3, "comment": "weak"},
            ],
            "overall_score": 45.0,
        }
        prompt = build_analyzer_prompt(eval_result, "dummy skill content")
        for cat in self._6_CATEGORIES:
            assert cat in prompt, (
                f"Category '{cat}' not found in analyzer prompt"
            )

    def test_analyzer_prompt_contains_priority_levels(self):
        """Verify high/medium/low priority levels are all mentioned."""
        from app.services.skill_eval.prompts import build_analyzer_prompt

        eval_result = {
            "dimensions": [{"key": "workflow", "score": 2, "comment": "weak"}],
            "overall_score": 30.0,
        }
        prompt = build_analyzer_prompt(eval_result, "dummy content")
        for level in ["high", "medium", "low"]:
            assert level in prompt, (
                f"Priority level '{level}' not found in analyzer prompt"
            )

    def test_analyzer_prompt_contains_eval_result(self):
        """Verify evaluation result data appears in the prompt."""
        from app.services.skill_eval.prompts import build_analyzer_prompt

        eval_result = {"dimensions": [
            {"key": "frontmatter", "score": 2, "comment": "Missing description"},
            {"key": "workflow", "score": 4, "comment": "Vague steps"},
        ], "overall_score": 30.0, "summary": "Poor overall quality"}
        prompt = build_analyzer_prompt(eval_result, "content")
        assert "frontmatter" in prompt, "Eval result dimensions must appear in prompt"
        assert "workflow" in prompt, "Eval result dimensions must appear in prompt"
        assert "30.0" in prompt, "Overall score must appear in prompt"

    def test_analyzer_prompt_contains_skill_content(self):
        """Verify skill content appears in the prompt."""
        from app.services.skill_eval.prompts import build_analyzer_prompt

        skill_content = "---\nname: weak-skill\n---\n\nSome body text."
        prompt = build_analyzer_prompt(
            {"dimensions": [], "overall_score": 50.0},
            skill_content,
        )
        assert skill_content in prompt, (
            "Analyzer prompt must include the skill content for optimization"
        )

    def test_analyzer_prompt_asks_for_json_output(self):
        """Verify prompt asks for JSON output matching OptimizationResult."""
        from app.services.skill_eval.prompts import build_analyzer_prompt

        prompt = build_analyzer_prompt({"dimensions": [], "overall_score": 0}, "c")
        assert "JSON" in prompt, "Analyzer prompt must require JSON output"
        assert "OptimizationResult" in prompt or "optimization" in prompt.lower(), (
            "Analyzer prompt must reference OptimizationResult schema"
        )

    def test_analyzer_prompt_mentions_root_cause(self):
        """Verify prompt asks to identify root causes for low scores."""
        from app.services.skill_eval.prompts import build_analyzer_prompt

        prompt = build_analyzer_prompt({"dimensions": [], "overall_score": 50.0}, "c")
        assert "根因" in prompt or "root" in prompt.lower() or "原因" in prompt, (
            "Analyzer prompt must ask to identify root causes"
        )


class TestAllExports:
    """Verify __init__.py exports all three builders."""

    def test_all_exports_contains_builders(self):
        """__all__ should list the three builder functions."""
        from app.services.skill_eval.prompts import __all__ as exports

        assert "build_grader_prompt" in exports
        assert "build_comparator_prompt" in exports
        assert "build_analyzer_prompt" in exports
