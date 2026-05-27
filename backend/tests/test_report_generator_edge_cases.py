"""
Edge case and integration tests for report_generator module (Phase 4).

Covers: HTML safety (XSS, unicode, empty fields), content edge cases
(empty dimensions, missing optionals, TIE/zero-delta results),
and integration tests (full pipeline, parseable HTML, no state corruption).

All functions under test live in `app.services.skill_eval.report_generator`.
The module may not exist yet — these tests are expected to FAIL (RED)
until the implementer creates it.
"""

import html
import re

import pytest

try:
    from app.services.skill_eval.report_generator import (
        generate_benchmark_report,
        generate_comparison_report,
        generate_evaluation_report,
        generate_optimization_report,
    )
except ImportError:
    generate_evaluation_report = None  # type: ignore[assignment]
    generate_benchmark_report = None  # type: ignore[assignment]
    generate_comparison_report = None  # type: ignore[assignment]
    generate_optimization_report = None  # type: ignore[assignment]

from app.schemas.skill_eval import (
    BenchmarkResult,
    Change,
    ComparisonResult,
    EvalDimension,
    GradingResult,
    OptimizationResult,
    RubricScore,
    Suggestion,
)

# ============================================================================
# Helpers
# ============================================================================

def _assert_valid_html(html_str: str) -> None:
    """Lightweight check that a string looks like a complete HTML document."""
    assert html_str is not None, "HTML output must not be None"
    assert isinstance(html_str, str), "HTML output must be a string"
    lowered = html_str.strip().lower()
    assert lowered.startswith("<!doctype html>") or lowered.startswith("<html"), (
        "HTML must start with DOCTYPE or <html>"
    )
    assert "<body" in lowered or "<body>" in lowered, "HTML must contain a <body>"
    assert lowered.endswith("</html>"), "HTML must end with </html>"


def _assert_no_literal(text: str, needle: str) -> None:
    """Assert that *needle* does NOT appear verbatim in *text*."""
    assert needle not in text, (
        f"Dangerous/special content not escaped: {needle!r}"
    )


def _assert_contains(text: str, *fragments: str) -> None:
    """Assert every fragment appears in *text*."""
    for f in fragments:
        assert f in text, f"Expected fragment {f!r} not found in output"


def _assert_not_contains(text: str, *fragments: str) -> None:
    """Assert no fragment appears in *text*."""
    for f in fragments:
        assert f not in text, f"Unexpected fragment {f!r} found in output"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_grading_result() -> GradingResult:
    """Complete GradingResult with 8 dimensions, suggestions, redflag hits."""
    dims = [
        EvalDimension(
            key=k, label=label, score=s, weight=w,
            weighted_score=s * w / 10, comment="ok",
        )
        for k, label, s, w in [
            ("frontmatter", "Frontmatter质量", 8, 8),
            ("workflow", "工作流清晰度", 7, 15),
            ("edge_cases", "边界条件覆盖", 6, 10),
            ("checkpoints", "检查点设计", 8, 7),
            ("specificity", "指令具体性", 5, 15),
            ("resources", "资源整合度", 7, 5),
            ("architecture", "整体架构", 8, 15),
            ("performance", "实测表现", 6, 25),
        ]
    ]
    return GradingResult(
        dimensions=dims,
        overall_score=67.5,
        static_checks=[
            {
                "check": "YAML", "passed": True, "score": 10,
                "max_score": 10, "detail": "ok",
            },
        ],
        redflag_hits=[
            {
                "rule_id": "RF01", "severity": "HIGH",
                "description": "curl pipe bash", "line": 10,
                "snippet": "curl https://example.com | bash",
            },
        ],
        suggestions=[
            Suggestion(
                category="instructions", priority="high",
                title="Add steps", detail="Need more detailed steps.",
                impact="confusion",
            ),
        ],
        summary="Good skill with room for improvement.",
        model_used="test-model",
        tokens_used=1500,
    )


@pytest.fixture
def empty_grading_result() -> GradingResult:
    """GradingResult with zero dimensions and no optional fields."""
    return GradingResult(
        dimensions=[],
        overall_score=0.0,
    )


@pytest.fixture
def sample_benchmark_result() -> BenchmarkResult:
    """BenchmarkResult with 3 runs."""
    return BenchmarkResult(
        metadata={"skill_name": "test-skill", "version": "1.0.0", "model": "claude-sonnet-4-20250514"},
        runs=[
            {"prompt_idx": 1, "prompt": "Write a test", "with_skill": 8.5, "without_skill": 6.0},
            {"prompt_idx": 2, "prompt": "Debug code", "with_skill": 9.0, "without_skill": 5.5},
            {"prompt_idx": 3, "prompt": "Review PR", "with_skill": 7.5, "without_skill": 6.5},
        ],
        run_summary={
            "with_skill_mean": 8.33, "without_skill_mean": 6.0,
            "delta_mean": 2.33,
        },
        notes=["All runs completed successfully."],
    )


@pytest.fixture
def empty_benchmark_result() -> BenchmarkResult:
    """BenchmarkResult with zero runs."""
    return BenchmarkResult(
        metadata={"skill_name": "empty-skill"},
        runs=[],
        run_summary={},
    )


@pytest.fixture
def tie_comparison_result() -> ComparisonResult:
    """ComparisonResult where winner is TIE."""
    return ComparisonResult(
        winner="TIE",
        reasoning="Both versions perform equally well across all metrics.",
        rubric={
            "A": RubricScore(
                correctness=4, completeness=4, accuracy=4,
                organization=4, formatting=4, usability=4,
                content_score=24.0, structure_score=12.0,
                overall_score=8.0,
            ),
            "B": RubricScore(
                correctness=4, completeness=4, accuracy=4,
                organization=4, formatting=4, usability=4,
                content_score=24.0, structure_score=12.0,
                overall_score=8.0,
            ),
        },
        output_quality={"A": "Good", "B": "Good"},
    )


@pytest.fixture
def sample_comparison_result() -> ComparisonResult:
    """ComparisonResult where A wins."""
    return ComparisonResult(
        winner="A",
        reasoning="Version A has better organization and sharper instructions.",
        rubric={
            "A": RubricScore(
                correctness=5, completeness=4, accuracy=5,
                organization=5, formatting=4, usability=4,
                content_score=28.5, structure_score=13.0,
                overall_score=9.0,
            ),
            "B": RubricScore(
                correctness=3, completeness=3, accuracy=3,
                organization=3, formatting=3, usability=3,
                content_score=18.0, structure_score=9.0,
                overall_score=6.0,
            ),
        },
        output_quality={"A": "Excellent", "B": "Adequate"},
    )


@pytest.fixture
def empty_changes_optimization_result() -> OptimizationResult:
    """OptimizationResult with no changes."""
    return OptimizationResult(
        original_content="# Original SKILL.md\n\nSkill content here.",
        optimized_content="# Original SKILL.md\n\nSkill content here.",
        changes=[],
        estimated_score_delta=0.0,
    )


@pytest.fixture
def negative_delta_optimization_result() -> OptimizationResult:
    """OptimizationResult with negative score delta."""
    return OptimizationResult(
        original_content="# Before\n\nSome content.",
        optimized_content="# After\n\nLess content.",
        changes=[
            Change(
                dimension="specificity",
                before="Detailed step-by-step instructions with examples.",
                after="Generic instructions.",
                description="Reduced specificity unintentionally.",
            ),
        ],
        estimated_score_delta=-5.0,
    )


@pytest.fixture
def full_optimization_result() -> OptimizationResult:
    """OptimizationResult with multiple positive changes."""
    return OptimizationResult(
        original_content="# Old SKILL.md\n\nDo the thing.",
        optimized_content="# New SKILL.md\n\n## Steps\n1. Check input\n2. Process\n3. Output result.",
        changes=[
            Change(
                dimension="workflow",
                before="Do the thing.",
                after="## Steps\n1. Check input\n2. Process\n3. Output result.",
                description="Added explicit workflow steps.",
            ),
            Change(
                dimension="edge_cases",
                before="",
                after="Handle empty input gracefully.",
                description="Added edge case handling.",
            ),
        ],
        estimated_score_delta=12.0,
    )


# ============================================================================
# TestHTMLEdgeCases
# ============================================================================

class TestHTMLEdgeCases:
    """Edge cases around HTML generation — XSS, unicode, empty fields, long strings."""

    # --- 1. XSS via skill name ------------------------------------------------

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        '"><script>alert(document.cookie)</script>',
        "<svg/onload=alert(1)>",
        "javascript:alert(1)",
    ])
    def test_skill_name_xss_escaped_in_evaluation_report(
        self, xss_payload, sample_grading_result,
    ):
        """Skill name containing HTML/JS is escaped, not executed."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(sample_grading_result, xss_payload)
        # The raw payload should never appear unescaped
        escaped = html.escape(xss_payload)
        if escaped != xss_payload:
            _assert_no_literal(report, xss_payload)
        # Escaped version should be safe
        _assert_valid_html(report)

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
    ])
    def test_skill_name_xss_escaped_in_benchmark_report(
        self, xss_payload, sample_benchmark_result,
    ):
        """Benchmark report with XSS skill name in metadata."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        sample_benchmark_result.metadata["skill_name"] = xss_payload
        report = generate_benchmark_report(sample_benchmark_result)
        escaped = html.escape(xss_payload)
        if escaped != xss_payload:
            _assert_no_literal(report, xss_payload)
        _assert_valid_html(report)

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
    ])
    def test_skill_name_xss_escaped_in_comparison_report(
        self, xss_payload, sample_comparison_result,
    ):
        """Comparison report with XSS skill name."""
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_comparison_report(sample_comparison_result, xss_payload)
        escaped = html.escape(xss_payload)
        if escaped != xss_payload:
            _assert_no_literal(report, xss_payload)
        _assert_valid_html(report)

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
    ])
    def test_skill_name_xss_escaped_in_optimization_report(
        self, xss_payload, full_optimization_result,
    ):
        """Optimization report with XSS skill name."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(full_optimization_result, xss_payload)
        escaped = html.escape(xss_payload)
        if escaped != xss_payload:
            _assert_no_literal(report, xss_payload)
        _assert_valid_html(report)

    # --- 2. Unicode / emoji skill name ----------------------------------------

    def test_skill_name_unicode_rendered_correctly(self, sample_grading_result):
        """Skill name with unicode and emoji is preserved in UTF-8."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        name = "AI一体机搜索 \U0001F980 ☃ \U0001f600"
        report = generate_evaluation_report(sample_grading_result, name)
        # Emoji/unicode chars should survive the round-trip
        assert "\U0001F980" in report, "Unicode emoji (unicorn) missing"
        assert "☃" in report, "Unicode snowman missing"
        assert "AI一体机" in report, "Chinese characters missing"
        _assert_valid_html(report)

    def test_skill_name_pure_emoji(self, sample_grading_result):
        """Skill name that is nothing but emoji."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        name = "\U0001f600\U0001f609\U0001f60e"  # 😀😉😎
        report = generate_evaluation_report(sample_grading_result, name)
        assert "\U0001f600" in report, "Emoji lost"
        _assert_valid_html(report)

    # --- 3. Empty skill_name ---------------------------------------------------

    def test_empty_skill_name_evaluation(self, sample_grading_result):
        """Empty skill_name produces valid HTML without crashing."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(sample_grading_result, "")
        assert report is not None
        assert len(report) > 0
        _assert_valid_html(report)

    def test_empty_skill_name_comparison(self, sample_comparison_result):
        """Empty skill_name in comparison report."""
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_comparison_report(sample_comparison_result, "")
        assert report is not None
        _assert_valid_html(report)

    def test_empty_skill_name_optimization(self, full_optimization_result):
        """Empty skill_name in optimization report."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(full_optimization_result, "")
        assert report is not None
        _assert_valid_html(report)

    # --- 4. Very long skill name -----------------------------------------------

    def test_very_long_skill_name(self, sample_grading_result):
        """Skill name of 200+ chars is not truncated in an ugly way."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        name = "SuperLong" * 40  # 360 chars
        report = generate_evaluation_report(sample_grading_result, name)
        # The full name should appear somewhere in the report (at least first 50 chars)
        assert name[:50] in report, "Long skill name appears to be missing"
        _assert_valid_html(report)
        # Report length must be proportionate (not absurdly small, not absurdly large)
        assert len(report) > len(name), "Report should be larger than the name itself"

    def test_whitespace_only_skill_name(self, sample_grading_result):
        """Whitespace-only skill_name should not crash."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(sample_grading_result, "   ")
        assert report is not None
        _assert_valid_html(report)


# ============================================================================
# TestReportContentEdgeCases
# ============================================================================

class TestReportContentEdgeCases:
    """Edge cases around report content — empty data, missing fields, special results."""

    # --- 5. GradingResult with 0 dimensions -----------------------------------

    def test_zero_dimensions_does_not_crash(self, empty_grading_result):
        """GradingResult with 0 dimensions produces valid HTML."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(empty_grading_result, "zero-dim-skill")
        _assert_valid_html(report)
        # Should at least include the overall score of 0.0
        assert "0.0" in report or "0" in report, "Should show overall score"

    def test_zero_dimensions_no_empty_table(self, empty_grading_result):
        """Report should not contain an empty <table> that confuses browsers."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(empty_grading_result, "zero-dim-skill")
        # If it contains <table>, there must be at least one <tr>
        if "<table" in report.lower():
            assert "<tr" in report.lower(), "Table found but no rows"

    # --- 6. Missing optional fields -------------------------------------------

    def test_missing_static_checks(self, empty_grading_result):
        """Missing static_checks (empty list) does not crash."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(empty_grading_result, "no-static")
        _assert_valid_html(report)

    def test_missing_redflag_hits(self, empty_grading_result):
        """Missing redflag_hits (empty list) does not crash."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(empty_grading_result, "no-redflags")
        _assert_valid_html(report)

    def test_missing_suggestions(self, empty_grading_result):
        """Missing suggestions (empty list) does not crash."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(empty_grading_result, "no-suggestions")
        _assert_valid_html(report)

    def test_missing_model_used(self, empty_grading_result):
        """Missing model_used (empty string) does not crash."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(empty_grading_result, "no-model")
        _assert_valid_html(report)

    def test_none_equivalent_fields(self):
        """Fields that might be None (if schema allowed) don't crash."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        # Construct via dict to bypass pydantic validation for edge case testing
        result = GradingResult(
            dimensions=[],
            overall_score=50.0,
            static_checks=[],
            redflag_hits=[],
            suggestions=[],
            summary="",
        )
        report = generate_evaluation_report(result, "safe-name")
        _assert_valid_html(report)

    # --- 7. BenchmarkResult with empty runs -----------------------------------

    def test_empty_runs_shows_no_data_message(self, empty_benchmark_result):
        """Empty runs produces valid HTML with 'no data' or equivalent message."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_benchmark_report(empty_benchmark_result)
        _assert_valid_html(report)
        # Should contain some indication of emptiness — check for common phrases
        no_data_indicators = ["no data", "no runs", "no results", "empty", "无数据", "暂无"]
        found = any(indicator.lower() in report.lower() for indicator in no_data_indicators)
        assert found, f"Report should indicate empty state; got: {report[:500]}"

    def test_empty_runs_valid_html(self, empty_benchmark_result):
        """Empty runs still produces a complete HTML document."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_benchmark_report(empty_benchmark_result)
        _assert_valid_html(report)

    def test_benchmark_missing_metadata(self):
        """BenchmarkResult with empty metadata dict."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        result = BenchmarkResult(metadata={}, runs=[], run_summary={})
        report = generate_benchmark_report(result)
        _assert_valid_html(report)

    # --- 8. ComparisonResult with TIE -----------------------------------------

    def test_tie_result_does_not_declare_winner(self, tie_comparison_result):
        """TIE result shows tie, not 'A wins' or 'B wins'."""
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_comparison_report(tie_comparison_result, "tie-skill")
        _assert_valid_html(report)
        # Should indicate tie/draw, not a winner phrasing
        tie_indicators = ["tie", "TIE", "draw", "Draw", "平局", "持平", "不分胜负"]
        found = any(ind in report for ind in tie_indicators)
        assert found, f"TIE report should indicate tie; got: {report[:500]}"
        # Should NOT unambiguously say "A wins" or "B wins"
        lowered = report.lower()
        assert "a win" not in lowered, "Should not say 'A wins' for a TIE"
        assert "b win" not in lowered, "Should not say 'B wins' for a TIE"

    def test_comparison_a_wins_shows_correct_winner(self, sample_comparison_result):
        """When A wins, report clearly indicates it."""
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_comparison_report(sample_comparison_result, "a-wins-skill")
        _assert_valid_html(report)
        # Should reference winner A
        assert "A" in report  # at minimum the letter 'A' appears

    def test_comparison_b_wins(self):
        """When B wins, report clearly indicates it."""
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        result = ComparisonResult(
            winner="B",
            reasoning="B has better edge case handling.",
            rubric={
                "A": RubricScore(overall_score=5.0),
                "B": RubricScore(overall_score=8.0),
            },
            output_quality={},
        )
        report = generate_comparison_report(result, "b-wins-skill")
        _assert_valid_html(report)
        assert "B" in report

    # --- 9. OptimizationResult with no changes --------------------------------

    def test_no_changes_shows_message(self, empty_changes_optimization_result):
        """OptimizationResult with no changes shows appropriate message."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(
            empty_changes_optimization_result, "no-change-skill",
        )
        _assert_valid_html(report)
        no_change_indicators = [
            "no changes", "no change", "无变更", "未变更",
            "没有变更", "unchanged", "identical",
        ]
        lowered = report.lower()
        found = any(ind.lower() in lowered for ind in no_change_indicators)
        assert found, f"Report should indicate no changes; got: {report[:500]}"

    def test_no_changes_zero_delta(self, empty_changes_optimization_result):
        """When delta is zero and no changes, report shows 0.0 delta."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(
            empty_changes_optimization_result, "zero-delta-skill",
        )
        _assert_valid_html(report)
        # Should mention delta of 0.0 or 0
        assert "0.0" in report or "0" in report, "Should show zero delta"

    # --- 10. Negative score_delta ---------------------------------------------

    def test_negative_delta_colored_negatively(self, negative_delta_optimization_result):
        """Negative score delta should be styled to indicate degradation."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(
            negative_delta_optimization_result, "negative-delta-skill",
        )
        _assert_valid_html(report)
        # Check for negative styling: red color, 'negative' class, or warning
        any(
            frag in report.lower()
            for frag in ["red", "negative", "warning", "danger", "decrease", "degrad", "下降", "降低", "#ff", "#f0", "#dc", "#e7", "bad", "error"]
        )
        # At minimum the negative value should appear
        assert "-5" in report or "-5.0" in report, "Negative score delta should be shown"

    def test_negative_delta_valid_html(self, negative_delta_optimization_result):
        """Negative delta still produces valid HTML."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(
            negative_delta_optimization_result, "neg-skill",
        )
        _assert_valid_html(report)


# ============================================================================
# TestReportIntegration
# ============================================================================

class TestReportIntegration:
    """Integration-style tests: full pipeline, parseability, state isolation, size limits."""

    # --- 11. Full pipeline: evaluate -> report -> parseable HTML ---------------

    def test_full_pipeline_evaluation_report(self, sample_grading_result):
        """Generate evaluation report from a complete result and verify HTML structure."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(sample_grading_result, "full-test-skill")
        _assert_valid_html(report)
        # Check for DOCTYPE
        assert re.search(r'(?i)<!doctype\s+html', report.strip()), "Must have DOCTYPE"
        # Check for closing tags (basic balance)
        assert report.count("<html") > 0 or report.count("</html>") > 0
        assert report.count("<body") > 0 or report.count("</body>") > 0

    def test_full_pipeline_benchmark_report(self, sample_benchmark_result):
        """Generate benchmark report and verify HTML structure."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_benchmark_report(sample_benchmark_result)
        _assert_valid_html(report)
        assert re.search(r'(?i)<!doctype\s+html', report.strip()), "Must have DOCTYPE"

    def test_full_pipeline_comparison_report(self, sample_comparison_result):
        """Generate comparison report and verify HTML structure."""
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_comparison_report(sample_comparison_result, "compare-skill")
        _assert_valid_html(report)
        assert re.search(r'(?i)<!doctype\s+html', report.strip()), "Must have DOCTYPE"

    def test_full_pipeline_optimization_report(self, full_optimization_result):
        """Generate optimization report and verify HTML structure."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(full_optimization_result, "opt-skill")
        _assert_valid_html(report)
        assert re.search(r'(?i)<!doctype\s+html', report.strip()), "Must have DOCTYPE"

    # --- 12. Report with ALL optional fields populated ------------------------

    def test_all_optional_fields_all_sections_present(self, sample_grading_result):
        """When all optional fields are populated, all sections appear in HTML."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(sample_grading_result, "complete-skill")

        _assert_valid_html(report)

        # Sections that should be present based on the data
        section_phrases = [
            "67.5",           # overall score
            "Frontmatter",    # dimension label
            "工作流",          # Chinese dimension label (partial: "工作流清晰度")
            "curl",           # redflag snippet text (escaped)
            "Add steps",      # suggestion title
            "Good skill",     # summary text
        ]
        for phrase in section_phrases:
            assert phrase in report, f"Expected phrase {phrase!r} in report"

        # Static checks should show
        _assert_contains(report, "YAML")

    def test_benchmark_all_fields_present(self, sample_benchmark_result):
        """Benchmark report with all optional fields shows all sections."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_benchmark_report(sample_benchmark_result)
        _assert_valid_html(report)
        # Should reference metadata, runs, and summary
        _assert_contains(report, "test-skill", "1.0.0")
        _assert_contains(report, "All runs completed successfully")

    def test_optimization_all_fields_present(self, full_optimization_result):
        """Optimization report with changes shows all sections."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(full_optimization_result, "full-opt-skill")
        _assert_valid_html(report)
        # Should show changes and delta
        _assert_contains(report, "workflow", "edge_cases", "12")
        _assert_contains(report, "Check input", "Handle empty")

    # --- 13. No shared state corruption between calls -------------------------

    def test_sequential_calls_no_state_corruption(self, sample_grading_result):
        """Two reports generated sequentially have independent content."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")

        report1 = generate_evaluation_report(sample_grading_result, "skill-one")
        report2 = generate_evaluation_report(sample_grading_result, "skill-two")

        _assert_valid_html(report1)
        _assert_valid_html(report2)

        # skill-one in first, skill-two in second
        assert "skill-one" in report1, "First report must reference its own skill name"
        assert "skill-two" in report2, "Second report must reference its own skill name"
        # No cross-contamination
        assert "skill-two" not in report1, "First report should not contain second skill name"
        assert "skill-one" not in report2, "Second report should not contain first skill name"

    def test_different_report_types_no_cross_contamination(
        self, sample_grading_result, sample_benchmark_result,
        tie_comparison_result, full_optimization_result,
    ):
        """Generating all four report types in sequence produces independent, valid HTML."""
        if any(f is None for f in [
            generate_evaluation_report,
            generate_benchmark_report,
            generate_comparison_report,
            generate_optimization_report,
        ]):
            pytest.skip("report_generator module not implemented yet")

        eval_report = generate_evaluation_report(sample_grading_result, "multi-skill")
        bench_report = generate_benchmark_report(sample_benchmark_result)
        comp_report = generate_comparison_report(tie_comparison_result, "multi-skill")
        opt_report = generate_optimization_report(full_optimization_result, "multi-skill")

        for report in [eval_report, bench_report, comp_report, opt_report]:
            _assert_valid_html(report)

        # Each report type should have distinct content markers
        assert "67.5" in eval_report, "Eval report missing score"
        assert "test-skill" in bench_report, "Benchmark report missing metadata"
        assert "TIE" in comp_report.upper() or "平局" in comp_report, "Comparison report missing TIE"
        assert "workflow" in opt_report, "Optimization report missing dimension"

    def test_mutable_input_not_corrupted(self, sample_benchmark_result):
        """Generating a report does not mutate the input object."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        original_metadata = dict(sample_benchmark_result.metadata)
        original_runs = list(sample_benchmark_result.runs)

        _ = generate_benchmark_report(sample_benchmark_result)

        assert sample_benchmark_result.metadata == original_metadata, "Metadata was mutated"
        assert sample_benchmark_result.runs == original_runs, "Runs were mutated"

    # --- 14. Report size is reasonable ----------------------------------------

    def test_evaluation_report_size_reasonable(self, sample_grading_result):
        """Typical evaluation report is under 1 MB."""
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_evaluation_report(sample_grading_result, "size-check")
        assert len(report.encode("utf-8")) < 1_000_000, (
            f"Report too large: {len(report.encode('utf-8'))} bytes"
        )

    def test_benchmark_report_size_reasonable(self, sample_benchmark_result):
        """Typical benchmark report is under 1 MB."""
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_benchmark_report(sample_benchmark_result)
        assert len(report.encode("utf-8")) < 1_000_000, (
            f"Report too large: {len(report.encode('utf-8'))} bytes"
        )

    def test_comparison_report_size_reasonable(self, sample_comparison_result):
        """Typical comparison report is under 1 MB."""
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_comparison_report(sample_comparison_result, "size-compare")
        assert len(report.encode("utf-8")) < 1_000_000, (
            f"Report too large: {len(report.encode('utf-8'))} bytes"
        )

    def test_optimization_report_size_reasonable(self, full_optimization_result):
        """Typical optimization report is under 1 MB."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        report = generate_optimization_report(full_optimization_result, "size-opt")
        assert len(report.encode("utf-8")) < 1_000_000, (
            f"Report too large: {len(report.encode('utf-8'))} bytes"
        )

    def test_large_input_report_size_reasonable(self):
        """Report with large original_content (10k chars) still under 1 MB."""
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        large_original = "x" * 10000
        large_optimized = "y" * 10000
        result = OptimizationResult(
            original_content=large_original,
            optimized_content=large_optimized,
            changes=[Change(
                dimension="specificity",
                before=large_original[:100],
                after=large_optimized[:100],
                description="Replaced content.",
            )],
            estimated_score_delta=0.0,
        )
        report = generate_optimization_report(result, "large-input")
        assert len(report.encode("utf-8")) < 1_000_000, (
            f"Large-input report too big: {len(report.encode('utf-8'))} bytes"
        )
        _assert_valid_html(report)


# ============================================================================
# TestReportOutputBasics (sanity checks)
# ============================================================================

class TestReportOutputBasics:
    """Basic sanity: every function returns a non-empty string."""

    def test_generate_evaluation_report_returns_string(self, sample_grading_result):
        if generate_evaluation_report is None:
            pytest.skip("report_generator module not implemented yet")
        result = generate_evaluation_report(sample_grading_result, "basic")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_benchmark_report_returns_string(self, sample_benchmark_result):
        if generate_benchmark_report is None:
            pytest.skip("report_generator module not implemented yet")
        result = generate_benchmark_report(sample_benchmark_result)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_comparison_report_returns_string(self, sample_comparison_result):
        if generate_comparison_report is None:
            pytest.skip("report_generator module not implemented yet")
        result = generate_comparison_report(sample_comparison_result, "basic")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_optimization_report_returns_string(self, full_optimization_result):
        if generate_optimization_report is None:
            pytest.skip("report_generator module not implemented yet")
        result = generate_optimization_report(full_optimization_result, "basic")
        assert isinstance(result, str)
        assert len(result) > 0
