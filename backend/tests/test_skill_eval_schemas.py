"""
Test skill evaluation Pydantic schemas.

Tests EvalDimension, GradingResult, ComparisonResult, Suggestion,
OptimizationResult, BenchmarkResult, and SkillEvalResultResponse.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


class TestEvalDimension:
    """Test EvalDimension creation and weighted_score calculation."""

    def test_dimension_creation(self):
        """EvalDimension should be created with all required fields."""
        from app.schemas.skill_eval import EvalDimension

        dim = EvalDimension(
            key="frontmatter",
            label="Frontmatter质量",
            score=8,
            max_score=10,
            weight=8,
            weighted_score=6.4,
            comment="Good frontmatter",
            evidence="name: my-skill",
        )
        assert dim.key == "frontmatter"
        assert dim.score == 8
        assert dim.weight == 8
        assert dim.weighted_score == 6.4

    def test_weighted_score_calculation(self):
        """Verify weighted_score = score * weight / 10 for each darwin dimension."""
        from app.schemas.skill_eval import EvalDimension

        # All 8 darwin dimensions with their weights
        dims = [
            EvalDimension(
                key=k, label=label, score=10, max_score=10, weight=w,
                weighted_score=round(10 * w / 10, 1), comment="", evidence="",
            )
            for k, label, w in [
                ("frontmatter", "Frontmatter质量", 8),
                ("workflow", "工作流清晰度", 15),
                ("edge_cases", "边界条件覆盖", 10),
                ("checkpoints", "检查点设计", 7),
                ("specificity", "指令具体性", 15),
                ("resources", "资源整合度", 5),
                ("architecture", "整体架构", 15),
                ("performance", "实测表现", 25),
            ]
        ]
        expected = [8.0, 15.0, 10.0, 7.0, 15.0, 5.0, 15.0, 25.0]
        for dim, exp in zip(dims, expected):
            assert dim.weighted_score == exp, f"{dim.key}: {dim.weighted_score} != {exp}"

    def test_default_max_score_is_10(self):
        """max_score should default to 10."""
        from app.schemas.skill_eval import EvalDimension

        dim = EvalDimension(
            key="frontmatter", label="Test", score=5,
            weight=8, weighted_score=4.0, comment="",
        )
        assert dim.max_score == 10

    def test_default_comment_and_evidence(self):
        """comment and evidence should default to empty string."""
        from app.schemas.skill_eval import EvalDimension

        dim = EvalDimension(
            key="frontmatter", label="Test", score=5,
            weight=8, weighted_score=4.0,
        )
        assert dim.comment == ""
        assert dim.evidence == ""


class TestScoreValidation:
    """Validation: score must be 1-10."""

    def test_score_too_low(self):
        """score < 1 should raise ValidationError."""
        from app.schemas.skill_eval import EvalDimension

        with pytest.raises(ValidationError):
            EvalDimension(
                key="frontmatter", label="Test", score=0,
                weight=8, weighted_score=0.0, comment="",
            )

    def test_score_too_high(self):
        """score > 10 should raise ValidationError."""
        from app.schemas.skill_eval import EvalDimension

        with pytest.raises(ValidationError):
            EvalDimension(
                key="frontmatter", label="Test", score=11,
                weight=8, weighted_score=8.8, comment="",
            )

    def test_score_valid_boundaries(self):
        """score=1 and score=10 should be valid."""
        from app.schemas.skill_eval import EvalDimension

        dim1 = EvalDimension(
            key="frontmatter", label="Test", score=1,
            weight=8, weighted_score=0.8, comment="",
        )
        assert dim1.score == 1

        dim10 = EvalDimension(
            key="frontmatter", label="Test", score=10,
            weight=8, weighted_score=8.0, comment="",
        )
        assert dim10.score == 10


class TestSuggestion:
    """Test Suggestion creation and validation."""

    def test_suggestion_creation(self):
        """Suggestion should be created with valid fields."""
        from app.schemas.skill_eval import Suggestion

        sug = Suggestion(
            category="instructions",
            priority="high",
            title="Add clearer instructions",
            detail="The workflow section is vague.",
            impact="LLM may misunderstand the task flow.",
        )
        assert sug.category == "instructions"
        assert sug.priority == "high"

    def test_suggestion_default_impact(self):
        """impact should default to empty string."""
        from app.schemas.skill_eval import Suggestion

        sug = Suggestion(
            category="structure",
            priority="medium",
            title="Reorganize sections",
            detail="Move checkpoints before examples.",
        )
        assert sug.impact == ""

    def test_priority_must_be_valid(self):
        """priority must be high/medium/low."""
        from app.schemas.skill_eval import Suggestion

        with pytest.raises(ValidationError):
            Suggestion(
                category="instructions",
                priority="urgent",  # invalid
                title="Test",
                detail="Test",
            )

    def test_priority_valid_values(self):
        """high, medium, low should all be accepted."""
        from app.schemas.skill_eval import Suggestion

        for p in ["high", "medium", "low"]:
            sug = Suggestion(
                category="instructions", priority=p,
                title="Test", detail="Test",
            )
            assert sug.priority == p

    def test_category_must_be_valid(self):
        """category must be from valid set."""
        from app.schemas.skill_eval import Suggestion

        with pytest.raises(ValidationError):
            Suggestion(
                category="invalid_category",
                priority="medium",
                title="Test",
                detail="Test",
            )

    def test_category_valid_values(self):
        """All valid categories should be accepted."""
        from app.schemas.skill_eval import Suggestion

        valid_categories = [
            "instructions", "tools", "examples",
            "error_handling", "structure", "references",
        ]
        for cat in valid_categories:
            sug = Suggestion(
                category=cat, priority="low",
                title="Test", detail="Test",
            )
            assert sug.category == cat


class TestGradingResult:
    """Test GradingResult with 8 dimensions."""

    def _make_dimension(self, key, label, weight, score=8):
        """Helper to create an EvalDimension."""
        from app.schemas.skill_eval import EvalDimension
        return EvalDimension(
            key=key,
            label=label,
            score=score,
            max_score=10,
            weight=weight,
            weighted_score=round(score * weight / 10, 1),
            comment="ok",
            evidence="",
        )

    def test_grading_result_with_8_dimensions(self):
        """GradingResult should accept 8 dimensions and produce correct overall_score."""
        from app.schemas.skill_eval import GradingResult

        darwin_dims = [
            self._make_dimension("frontmatter", "Frontmatter质量", 8),
            self._make_dimension("workflow", "工作流清晰度", 15),
            self._make_dimension("edge_cases", "边界条件覆盖", 10),
            self._make_dimension("checkpoints", "检查点设计", 7),
            self._make_dimension("specificity", "指令具体性", 15),
            self._make_dimension("resources", "资源整合度", 5),
            self._make_dimension("architecture", "整体架构", 15),
            self._make_dimension("performance", "实测表现", 25),
        ]
        result = GradingResult(
            dimensions=darwin_dims,
            overall_score=sum(d.weighted_score for d in darwin_dims),
            summary="Good skill overall.",
            model_used="claude-4",
        )
        expected_score = sum(
            round(8 * w / 10, 1) for w in [8, 15, 10, 7, 15, 5, 15, 25]
        )
        assert result.overall_score == expected_score

    def test_grading_result_perfect_score(self):
        """All 10s should give overall_score 100.0."""
        from app.schemas.skill_eval import GradingResult

        darwin_dims = [
            self._make_dimension(k, label, w, score=10)
            for k, label, w in [
                ("frontmatter", "Frontmatter质量", 8),
                ("workflow", "工作流清晰度", 15),
                ("edge_cases", "边界条件覆盖", 10),
                ("checkpoints", "检查点设计", 7),
                ("specificity", "指令具体性", 15),
                ("resources", "资源整合度", 5),
                ("architecture", "整体架构", 15),
                ("performance", "实测表现", 25),
            ]
        ]
        result = GradingResult(
            dimensions=darwin_dims,
            overall_score=sum(d.weighted_score for d in darwin_dims),
            summary="Perfect!",
        )
        assert result.overall_score == 100.0

    def test_grading_result_defaults(self):
        """static_checks, redflag_hits, suggestions should default to empty lists."""
        from app.schemas.skill_eval import GradingResult

        darwin_dims = [
            self._make_dimension(k, label, w)
            for k, label, w in [
                ("frontmatter", "Frontmatter质量", 8),
                ("workflow", "工作流清晰度", 15),
                ("edge_cases", "边界条件覆盖", 10),
                ("checkpoints", "检查点设计", 7),
                ("specificity", "指令具体性", 15),
                ("resources", "资源整合度", 5),
                ("architecture", "整体架构", 15),
                ("performance", "实测表现", 25),
            ]
        ]
        result = GradingResult(
            dimensions=darwin_dims,
            overall_score=sum(d.weighted_score for d in darwin_dims),
            summary="Test",
        )
        assert result.static_checks == []
        assert result.redflag_hits == []
        assert result.suggestions == []
        assert result.model_used == ""
        assert result.tokens_used == 0

    def test_grading_result_with_suggestions(self):
        """GradingResult should accept suggestions list."""
        from app.schemas.skill_eval import GradingResult, Suggestion

        darwin_dims = [
            self._make_dimension(k, label, w)
            for k, label, w in [
                ("frontmatter", "Frontmatter质量", 8),
                ("workflow", "工作流清晰度", 15),
                ("edge_cases", "边界条件覆盖", 10),
                ("checkpoints", "检查点设计", 7),
                ("specificity", "指令具体性", 15),
                ("resources", "资源整合度", 5),
                ("architecture", "整体架构", 15),
                ("performance", "实测表现", 25),
            ]
        ]
        suggestions = [
            Suggestion(
                category="instructions", priority="high",
                title="Add examples", detail="Missing input/output examples.",
            ),
            Suggestion(
                category="structure", priority="medium",
                title="Reorder sections", detail="Workflow should come before edge cases.",
            ),
        ]
        result = GradingResult(
            dimensions=darwin_dims,
            overall_score=75.0,
            suggestions=suggestions,
            summary="Needs improvement.",
        )
        assert len(result.suggestions) == 2
        assert result.suggestions[0].category == "instructions"


class TestRubricScore:
    """Test RubricScore used in ComparisonResult."""

    def test_rubric_score_defaults(self):
        """All rubric score fields should default to 0."""
        from app.schemas.skill_eval import RubricScore

        rs = RubricScore()
        assert rs.correctness == 0
        assert rs.completeness == 0
        assert rs.content_score == 0.0
        assert rs.structure_score == 0.0
        assert rs.overall_score == 0.0


class TestComparisonResult:
    """Test ComparisonResult with rubric scores."""

    def test_comparison_winner_a(self):
        """ComparisonResult with winner='A'."""
        from app.schemas.skill_eval import ComparisonResult, RubricScore

        rubric_a = RubricScore(
            correctness=4, completeness=4, accuracy=3,
            organization=4, formatting=5, usability=4,
            content_score=7.3, structure_score=8.7, overall_score=8.0,
        )
        rubric_b = RubricScore(
            correctness=3, completeness=3, accuracy=2,
            organization=3, formatting=4, usability=3,
            content_score=5.3, structure_score=6.7, overall_score=6.0,
        )
        result = ComparisonResult(
            winner="A",
            reasoning="A has better instructions.",
            rubric={"A": rubric_a, "B": rubric_b},
            output_quality={},
        )
        assert result.winner == "A"
        assert result.rubric["A"].overall_score == 8.0
        assert result.rubric["B"].overall_score == 6.0

    def test_comparison_tie(self):
        """ComparisonResult with winner='TIE'."""
        from app.schemas.skill_eval import ComparisonResult, RubricScore

        r = RubricScore(overall_score=7.0)
        result = ComparisonResult(
            winner="TIE",
            reasoning="Both equally good.",
            rubric={"A": r, "B": r},
            output_quality={},
        )
        assert result.winner == "TIE"
        assert result.reasoning == "Both equally good."

    def test_comparison_invalid_winner(self):
        """Winner must be 'A', 'B', or 'TIE'."""
        from app.schemas.skill_eval import ComparisonResult, RubricScore

        with pytest.raises(ValidationError):
            ComparisonResult(
                winner="C",  # invalid
                reasoning="",
                rubric={"A": RubricScore(), "B": RubricScore()},
                output_quality={},
            )


class TestOptimizationResult:
    """Test OptimizationResult and Change."""

    def test_change_creation(self):
        """Change should be created with dimension, before, after, description."""
        from app.schemas.skill_eval import Change

        c = Change(
            dimension="workflow",
            before="Step 1 then Step 2",
            after="Step 1: Validate -> Step 2: Execute",
            description="Added validation step.",
        )
        assert c.dimension == "workflow"
        assert c.before == "Step 1 then Step 2"

    def test_optimization_result_creation(self):
        """OptimizationResult with changes list."""
        from app.schemas.skill_eval import Change, OptimizationResult

        changes = [
            Change(
                dimension="frontmatter",
                before="name: old",
                after="name: new-skill\ndescription: Better desc",
                description="Added description.",
            ),
        ]
        result = OptimizationResult(
            original_content="---\nname: old\n---\n\nBody",
            optimized_content="---\nname: new-skill\ndescription: Better desc\n---\n\nBody",
            changes=changes,
            estimated_score_delta=5.0,
        )
        assert len(result.changes) == 1
        assert result.estimated_score_delta == 5.0

    def test_optimization_result_defaults(self):
        """changes and estimated_score_delta should have defaults."""
        from app.schemas.skill_eval import OptimizationResult

        result = OptimizationResult(
            original_content="old",
            optimized_content="new",
        )
        assert result.changes == []
        assert result.estimated_score_delta == 0.0


class TestBenchmarkResult:
    """Test BenchmarkResult."""

    def test_benchmark_result_defaults(self):
        """All dict/list fields should default to empty."""
        from app.schemas.skill_eval import BenchmarkResult

        br = BenchmarkResult()
        assert br.metadata == {}
        assert br.runs == []
        assert br.run_summary == {}
        assert br.notes == []

    def test_benchmark_result_with_runs(self):
        """BenchmarkResult should accept run data."""
        from app.schemas.skill_eval import BenchmarkResult

        br = BenchmarkResult(
            metadata={"skill": "test-skill", "version": "1.0"},
            runs=[
                {"latency_ms": 1200, "tokens": 500},
                {"latency_ms": 1100, "tokens": 480},
            ],
            run_summary={
                "with_skill": {"avg_latency_ms": 1150},
                "without_skill": {"avg_latency_ms": 1400},
                "delta": {"avg_latency_ms": -250},
            },
            notes=["Improvement observed."],
        )
        assert len(br.runs) == 2
        assert br.run_summary["delta"]["avg_latency_ms"] == -250


class TestSkillEvalResultResponse:
    """Test SkillEvalResultResponse from_attributes."""

    def test_response_creation(self):
        """SkillEvalResultResponse should be creatable directly."""
        from app.schemas.skill_eval import (
            EvalDimension,
            SkillEvalResultResponse,
        )

        now = datetime.now(timezone.utc)
        dims = [
            EvalDimension(
                key="frontmatter", label="Frontmatter质量",
                score=8, weight=8, weighted_score=6.4,
                comment="ok",
            ),
        ]
        resp = SkillEvalResultResponse(
            id=1,
            skill_name="test-skill",
            eval_type="full",
            eval_mode="evaluate",
            overall_score=75.0,
            dimensions=dims,
            summary="Good skill.",
            model_used="claude-4",
            tokens_used=1500,
            creator_id=42,
            created_at=now,
        )
        assert resp.id == 1
        assert resp.skill_name == "test-skill"
        assert resp.eval_type == "full"
        assert resp.overall_score == 75.0
        assert len(resp.dimensions) == 1

    def test_response_from_attributes_via_model_config(self):
        """Verify model_config is set to from_attributes=True."""
        from app.schemas.skill_eval import SkillEvalResultResponse

        assert hasattr(SkillEvalResultResponse, "model_config")
        assert SkillEvalResultResponse.model_config.get("from_attributes") is True
