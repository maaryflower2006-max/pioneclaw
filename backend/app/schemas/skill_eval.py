"""
Pydantic schemas for skill evaluation.

Covers darwin-skill 8-dimension rubric, skill-creator grading/comparison/benchmark,
optimization results, and database response models.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ==================== EvalDimension (darwin-skill 8-dimension rubric) ====================

class EvalDimension(BaseModel):
    """Single dimension score in the darwin 8-dimension rubric.

    Weighted dimensions:
      - Structure (60 points total): frontmatter(8), workflow(15), edge_cases(10),
        checkpoints(7), specificity(15), resources(5)
      - Effectiveness (40 points total): architecture(15), performance(25)
    """
    key: str = Field(description="Dimension key: frontmatter|workflow|edge_cases|checkpoints|specificity|resources|architecture|performance")
    label: str = Field(description="Chinese label for the dimension")
    score: int = Field(ge=1, le=10, description="Score 1-10")
    max_score: int = Field(default=10, description="Maximum score (always 10)")
    weight: int = Field(description="Weight: 8|15|10|7|15|5|15|25")
    weighted_score: float = Field(description="score * weight / 10")
    comment: str = Field(default="", description="Evaluator comment")
    evidence: str = Field(default="", description="Quoted evidence from SKILL.md")


# ==================== Suggestion (skill-creator analyzer.md pattern) ====================

VALID_SUGGESTION_CATEGORIES = frozenset({
    "instructions", "tools", "examples",
    "error_handling", "structure", "references",
})
VALID_SUGGESTION_PRIORITIES = frozenset({"high", "medium", "low"})


class Suggestion(BaseModel):
    """Improvement suggestion from skill-creator analyzer.md pattern."""
    category: str = Field(description="Category: instructions|tools|examples|error_handling|structure|references")
    priority: Literal["high", "medium", "low"] = Field(description="Priority level")
    title: str = Field(description="Suggestion title")
    detail: str = Field(description="Detailed suggestion")
    impact: str = Field(default="", description="What happens if not fixed")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in VALID_SUGGESTION_CATEGORIES:
            raise ValueError(
                f"Invalid category '{v}'. Must be one of: "
                f"{', '.join(sorted(VALID_SUGGESTION_CATEGORIES))}"
            )
        return v


# ==================== GradingResult (skill-creator grading.json) ====================

class GradingResult(BaseModel):
    """Full evaluation result corresponding to skill-creator grading.json."""
    dimensions: list[EvalDimension] = Field(description="8-dimension scoring details")
    overall_score: float = Field(description="Sum of weighted_scores, max 100")
    static_checks: list[dict] = Field(default_factory=list, description="quick_validate results")
    redflag_hits: list[dict] = Field(default_factory=list, description="Security red flag scan hits")
    suggestions: list[Suggestion] = Field(default_factory=list, description="Improvement suggestions")
    summary: str = Field(default="", description="Overall evaluation summary")
    model_used: str = Field(default="", description="LLM model used for evaluation")
    tokens_used: int = Field(default=0, description="Tokens consumed")


# ==================== ComparisonResult (skill-creator comparison.json) ====================

class RubricScore(BaseModel):
    """Score breakdown for a single skill version in A/B comparison."""
    correctness: int = Field(default=0, ge=0, le=5, description="Content correctness (1-5)")
    completeness: int = Field(default=0, ge=0, le=5, description="Content completeness (1-5)")
    accuracy: int = Field(default=0, ge=0, le=5, description="Content accuracy (1-5)")
    organization: int = Field(default=0, ge=0, le=5, description="Structure organization (1-5)")
    formatting: int = Field(default=0, ge=0, le=5, description="Structure formatting (1-5)")
    usability: int = Field(default=0, ge=0, le=5, description="Structure usability (1-5)")
    content_score: float = Field(default=0.0, description="Aggregated content score")
    structure_score: float = Field(default=0.0, description="Aggregated structure score")
    overall_score: float = Field(default=0.0, description="Final overall score (1-10)")


class ComparisonResult(BaseModel):
    """A/B blind comparison result corresponding to skill-creator comparison.json."""
    winner: Literal["A", "B", "TIE"] = Field(description="Which version won")
    reasoning: str = Field(default="", description="Why the winner was chosen")
    rubric: dict[str, RubricScore] = Field(default_factory=dict, description="Rubric scores for A and B")
    output_quality: dict = Field(default_factory=dict, description="Output quality comparison")


# ==================== OptimizationResult ====================

class Change(BaseModel):
    """A single change in an optimization diff."""
    dimension: str = Field(description="Which dimension this change targets")
    before: str = Field(description="Text before the change")
    after: str = Field(description="Text after the change")
    description: str = Field(description="Human-readable description of the change")


class OptimizationResult(BaseModel):
    """Result of running skill-creator optimizer on a skill."""
    original_content: str = Field(description="Original SKILL.md content")
    optimized_content: str = Field(description="Optimized SKILL.md content")
    changes: list[Change] = Field(default_factory=list, description="List of changes made")
    estimated_score_delta: float = Field(default=0.0, description="Estimated score improvement")


# ==================== BenchmarkResult (skill-creator benchmark.json) ====================

class BenchmarkResult(BaseModel):
    """Benchmark result corresponding to skill-creator benchmark.json."""
    metadata: dict = Field(default_factory=dict, description="Benchmark metadata (skill name, version, etc.)")
    runs: list[dict] = Field(default_factory=list, description="Individual benchmark runs")
    run_summary: dict = Field(default_factory=dict, description="with_skill / without_skill / delta summary")
    notes: list[str] = Field(default_factory=list, description="Benchmark notes")


# ==================== Database Response Model ====================

class SkillEvalResultResponse(BaseModel):
    """API response model for a skill_eval_results row."""
    id: int
    skill_name: str
    eval_type: str
    eval_mode: str
    overall_score: float
    dimensions: list[dict] = []
    static_checks: Optional[list[dict]] = None
    redflag_hits: Optional[list[dict]] = None
    suggestions: Optional[list[dict]] = None
    summary: str
    model_used: str
    tokens_used: int
    creator_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
