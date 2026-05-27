"""Tests for report_generator module (Phase 4)."""
import pytest

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
from app.services.skill_eval.report_generator import (
    generate_benchmark_report,
    generate_comparison_report,
    generate_evaluation_report,
    generate_optimization_report,
)

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_dims():
    return [
        EvalDimension(key=k, label=label, score=s, weight=w, weighted_score=s*w/10, comment="ok")
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


@pytest.fixture
def sample_grading_result(sample_dims):
    return GradingResult(
        dimensions=list(sample_dims),
        overall_score=67.5,
        static_checks=[{"check": "YAML", "passed": True, "score": 10, "max_score": 10, "detail": "ok"}],
        redflag_hits=[{"rule_id": "RF01", "severity": "HIGH", "description": "curl pipe bash", "line": 10, "snippet": "curl | bash"}],
        suggestions=[Suggestion(category="instructions", priority="high", title="Add steps", detail="Missing steps", impact="confusion")],
        summary="Good skill.",
    )


@pytest.fixture
def sample_benchmark():
    return BenchmarkResult(
        metadata={"skill_name": "test", "executor_model": "claude-4", "timestamp": "2026-01-01", "evals_run": [1], "runs_per_configuration": 3},  # noqa: E501
        runs=[{"eval_id": 1, "configuration": "with_skill", "run_number": 1, "result": {"pass_rate": 0.85, "passed": 5, "total": 6, "time_seconds": 42.0, "tokens": 3800}}],  # noqa: E501
        run_summary={"with_skill": {"pass_rate": {"mean": 0.85}, "time_seconds": {"mean": 42.0}, "tokens": {"mean": 3800}}, "without_skill": {"pass_rate": {"mean": 0.35}, "time_seconds": {"mean": 32.0}, "tokens": {"mean": 2100}}, "delta": {"pass_rate": "+0.50"}},  # noqa: E501
        notes=["Improvement observed"],
    )


@pytest.fixture
def sample_comparison():
    return ComparisonResult(
        winner="A",
        reasoning="A has better instructions",
        rubric={"A": RubricScore(correctness=4, completeness=4, accuracy=3, content_score=3.7, structure_score=4.0, overall_score=7.7), "B": RubricScore(correctness=3, completeness=2, accuracy=3, content_score=2.7, structure_score=3.0, overall_score=5.7)},  # noqa: E501
    )


@pytest.fixture
def sample_optimization():
    return OptimizationResult(
        original_content="---\nname: old\n---\n\nBody",
        optimized_content="---\nname: new\ndescription: better\n---\n\nBetter body",
        changes=[Change(dimension="frontmatter", before="name: old", after="name: new", description="Added description")],
        estimated_score_delta=5.0,
    )


# ── Evaluation report tests ─────────────────────────────────────────────────

class TestEvaluationReport:
    def test_contains_skill_name(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result, skill_name="my-skill")
        assert "my-skill" in html

    def test_contains_overall_score(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        assert "67.5" in html

    def test_has_all_8_dimensions(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        for key in ["Frontmatter", "工作流", "边界条件", "检查点", "指令具体", "资源整合", "整体架构", "实测表现"]:
            assert key in html, f"Missing dimension: {key}"

    def test_is_valid_html(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "<head>" in html
        assert "<body>" in html

    def test_contains_suggestions(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        assert "Add steps" in html
        assert "Missing steps" in html

    def test_contains_redflag_hits(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        assert "RF01" in html
        assert "curl pipe bash" in html

    def test_contains_static_checks(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        assert "YAML" in html

    def test_empty_skill_name(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result, skill_name="")
        assert "<!DOCTYPE html>" in html

    def test_score_color_coding(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        assert "#f59e0b" in html or "var(--amber)" in html  # 67.5 is amber

    def test_no_external_dependencies(self, sample_grading_result):
        html = generate_evaluation_report(sample_grading_result)
        assert '<link rel="stylesheet"' not in html
        assert '<script src=' not in html

    def test_with_no_dimensions(self):
        result = GradingResult(dimensions=[], overall_score=50.0, summary="")
        html = generate_evaluation_report(result)
        assert "<!DOCTYPE html>" in html

    def test_with_no_optional_fields(self):
        result = GradingResult(dimensions=[], overall_score=0.0, summary="")
        html = generate_evaluation_report(result)
        assert "<!DOCTYPE html>" in html


# ── Benchmark report tests ──────────────────────────────────────────────────

class TestBenchmarkReport:
    def test_contains_configs(self, sample_benchmark):
        html = generate_benchmark_report(sample_benchmark)
        assert "with_skill" in html
        assert "without_skill" in html

    def test_contains_pass_rate(self, sample_benchmark):
        html = generate_benchmark_report(sample_benchmark)
        assert "85" in html

    def test_is_valid_html(self, sample_benchmark):
        html = generate_benchmark_report(sample_benchmark)
        assert "<!DOCTYPE html>" in html

    def test_contains_delta(self, sample_benchmark):
        html = generate_benchmark_report(sample_benchmark)
        assert "+0.50" in html

    def test_contains_notes(self, sample_benchmark):
        html = generate_benchmark_report(sample_benchmark)
        assert "Improvement observed" in html

    def test_empty_benchmark(self):
        bm = BenchmarkResult()
        html = generate_benchmark_report(bm)
        assert "<!DOCTYPE html>" in html

    def test_no_external_dependencies(self, sample_benchmark):
        html = generate_benchmark_report(sample_benchmark)
        assert '<link rel="stylesheet"' not in html
        assert '<script src=' not in html


# ── Comparison report tests ─────────────────────────────────────────────────

class TestComparisonReport:
    def test_contains_winner(self, sample_comparison):
        html = generate_comparison_report(sample_comparison)
        assert "A" in html  # winner

    def test_has_rubric_scores(self, sample_comparison):
        html = generate_comparison_report(sample_comparison)
        assert "7.7" in html or "7.7" in html

    def test_is_valid_html(self, sample_comparison):
        html = generate_comparison_report(sample_comparison)
        assert "<!DOCTYPE html>" in html

    def test_tie_result(self):
        comp = ComparisonResult(winner="TIE", reasoning="Both equal", rubric={
            "A": RubricScore(overall_score=7.0), "B": RubricScore(overall_score=7.0)
        })
        html = generate_comparison_report(comp)
        assert "TIE" in html


# ── Optimization report tests ───────────────────────────────────────────────

class TestOptimizationReport:
    def test_contains_changes(self, sample_optimization):
        html = generate_optimization_report(sample_optimization)
        assert "frontmatter" in html
        assert "Added description" in html

    def test_contains_score_delta(self, sample_optimization):
        html = generate_optimization_report(sample_optimization)
        assert "+5.0" in html

    def test_contains_optimized_content(self, sample_optimization):
        html = generate_optimization_report(sample_optimization)
        assert "Better body" in html

    def test_is_valid_html(self, sample_optimization):
        html = generate_optimization_report(sample_optimization)
        assert "<!DOCTYPE html>" in html

    def test_no_changes(self):
        result = OptimizationResult(original_content="old", optimized_content="new", changes=[], estimated_score_delta=0.0)
        html = generate_optimization_report(result)
        assert "<!DOCTYPE html>" in html
