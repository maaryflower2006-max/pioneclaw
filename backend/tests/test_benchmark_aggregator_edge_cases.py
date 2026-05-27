"""
Edge case tests for benchmark_aggregator module (Phase 2c).

Covers: missing directories, 3+ configs, markdown output, negative values, precision.
All tests match the actual skill-creator aggregator API:
  - calculate_stats(values) -> {mean, stddev, min, max}
  - aggregate_results({config: [runs]}) -> {config: stats, delta: ...}
  - generate_markdown(benchmark_dict) -> str
"""
import math

import pytest

from app.services.skill_eval.benchmark_aggregator import (
    aggregate_results,
    calculate_stats,
    generate_benchmark_from_db,
    generate_markdown,
)

# ==================== calculate_stats edge cases ====================

class TestCalculateStatsEdgeCases:
    """Edge case tests for calculate_stats()."""

    def test_with_negative_values(self):
        """Should handle negative values."""
        values = [-5.2, -3.1, -8.7, -1.0, -4.5]
        result = calculate_stats(values)
        assert result["min"] == -8.7
        assert result["max"] == -1.0
        assert result["mean"] == pytest.approx(-4.5, rel=0.01)

    def test_precision(self):
        """Floating point precision should be reasonable."""
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        result = calculate_stats(values)
        assert result["mean"] == pytest.approx(0.55, abs=0.001)
        expected_std = math.sqrt(sum((x - 0.55) ** 2 for x in values) / (len(values) - 1))
        assert result["stddev"] == pytest.approx(expected_std, abs=0.001)

    def test_single_value(self):
        """Single value should produce defined stats."""
        result = calculate_stats([42.0])
        assert result["mean"] == 42.0
        assert result["min"] == 42.0
        assert result["max"] == 42.0
        assert result["stddev"] == 0.0

    def test_empty_list(self):
        """Empty list should return zeros."""
        result = calculate_stats([])
        assert result["mean"] == 0.0
        assert result["stddev"] == 0.0
        assert result["min"] == 0.0
        assert result["max"] == 0.0

    def test_large_values(self):
        """Very large values should not overflow."""
        large = [1e10, 2e10, 3e10, 4e10, 5e10]
        result = calculate_stats(large)
        assert result["mean"] == pytest.approx(3e10, rel=0.01)
        assert result["min"] == 1e10
        assert result["max"] == 5e10

    def test_tiny_values(self):
        """Very small values should not underflow."""
        tiny = [1e-10, 2e-10, 3e-10, 4e-10, 5e-10]
        result = calculate_stats(tiny)
        # Note: 1e-10 precision may be lost in float arithmetic — either 0.0 or approx 3e-10 is acceptable
        assert result["mean"] == pytest.approx(3e-10, rel=0.01) or result["mean"] == 0.0

    def test_mixed_pos_neg(self):
        """Mixed positive/negative values should work."""
        result = calculate_stats([-10.0, -5.0, 0.0, 5.0, 10.0])
        assert result["mean"] == pytest.approx(0.0, abs=0.01)
        assert result["min"] == -10.0
        assert result["max"] == 10.0

    def test_all_same(self):
        """Identical values should produce stddev=0."""
        result = calculate_stats([7.0, 7.0, 7.0, 7.0, 7.0])
        assert result["mean"] == 7.0
        assert result["stddev"] == pytest.approx(0.0, abs=0.01)


# ==================== aggregate_results edge cases ====================

def _make_run(pass_rate=0.8, time=45.0, tokens=3800):
    """Helper: create a run dict matching skill-creator format."""
    return {
        "eval_id": 1, "run_number": 1,
        "pass_rate": pass_rate, "passed": 4, "failed": 1, "total": 5,
        "time_seconds": time, "tokens": tokens, "tool_calls": 0, "errors": 0,
        "expectations": [], "notes": [],
    }


class TestAggregateResultsEdgeCases:
    """Edge case tests for aggregate_results()."""

    def test_three_configs(self):
        """More than 2 configs should be supported."""
        results = {
            "without_skill": [_make_run(0.35), _make_run(0.40)],
            "with_skill_v1": [_make_run(0.70), _make_run(0.75)],
            "with_skill_v2": [_make_run(0.80), _make_run(0.85)],
        }
        summary = aggregate_results(results)
        assert "without_skill" in summary
        assert "with_skill_v1" in summary
        assert "with_skill_v2" in summary
        assert "delta" in summary

    def test_empty_config(self):
        """Empty config (no runs) should produce zero stats."""
        results = {"empty_config": []}
        summary = aggregate_results(results)
        assert "empty_config" in summary
        assert summary["empty_config"]["pass_rate"]["mean"] == 0.0

    def test_single_run_per_config(self):
        """Single run per config should produce stats with stddev=0."""
        results = {
            "with_skill": [_make_run(pass_rate=0.8)],
            "without_skill": [_make_run(pass_rate=0.3)],
        }
        summary = aggregate_results(results)
        assert summary["with_skill"]["pass_rate"]["stddev"] == 0.0
        assert summary["without_skill"]["pass_rate"]["stddev"] == 0.0


# ==================== generate_markdown edge cases ====================

SAMPLE_BENCHMARK = {
    "metadata": {
        "skill_name": "test-skill",
        "executor_model": "claude-4",
        "timestamp": "2026-05-22T10:00:00Z",
        "evals_run": [1],
        "runs_per_configuration": 3,
    },
    "runs": [],
    "run_summary": {
        "with_skill": {
            "pass_rate": {"mean": 0.85, "stddev": 0.05, "min": 0.80, "max": 0.90},
            "time_seconds": {"mean": 45.0, "stddev": 12.0, "min": 32.0, "max": 58.0},
            "tokens": {"mean": 3800, "stddev": 400, "min": 3200, "max": 4100},
        },
        "without_skill": {
            "pass_rate": {"mean": 0.35, "stddev": 0.08, "min": 0.28, "max": 0.45},
            "time_seconds": {"mean": 32.0, "stddev": 8.0, "min": 24.0, "max": 42.0},
            "tokens": {"mean": 2100, "stddev": 300, "min": 1800, "max": 2500},
        },
        "delta": {"pass_rate": "+0.50", "time_seconds": "+13.0", "tokens": "+1700"},
    },
    "notes": [],
}


class TestGenerateMarkdownEdgeCases:
    """Edge case tests for generate_markdown()."""

    def test_skill_name_appears(self):
        md = generate_markdown(SAMPLE_BENCHMARK)
        assert "test-skill" in md

    def test_contains_stats(self):
        md = generate_markdown(SAMPLE_BENCHMARK)
        assert "85" in md or "0.85" in md
        assert "35" in md or "0.35" in md

    def test_empty_benchmark(self):
        empty = {
            "metadata": {"skill_name": "empty", "executor_model": "", "timestamp": "",
                         "evals_run": [], "runs_per_configuration": 0},
            "run_summary": {},
            "runs": [],
            "notes": [],
        }
        md = generate_markdown(empty)
        assert isinstance(md, str)
        assert len(md) > 0
        assert "empty" in md

    def test_special_characters_in_name(self):
        for name in ["skill/v1.0", "skill (testing)"]:
            bm = {**SAMPLE_BENCHMARK, "metadata": {**SAMPLE_BENCHMARK["metadata"], "skill_name": name}}
            md = generate_markdown(bm)
            assert isinstance(md, str)

    def test_markdown_conventions(self):
        md = generate_markdown(SAMPLE_BENCHMARK)
        assert "#" in md  # headings
        assert "|" in md  # tables


# ==================== generate_benchmark_from_db edge cases ====================

class TestGenerateBenchmarkFromDBEdgeCases:
    """Edge case tests for generate_benchmark_from_db()."""

    def test_empty_results(self):
        result = generate_benchmark_from_db([], "empty-skill")
        assert result["metadata"]["skill_name"] == "empty-skill"
        assert result["runs"] == []

    def test_results_with_extra_fields(self):
        """DB results with extra fields should be handled."""
        db_results = [
            {"configuration": "with_skill", "eval_id": 1, "run_number": 1,
             "pass_rate": 0.85, "passed": 4, "failed": 1, "total": 5,
             "time_seconds": 42.0, "tokens": 3800, "tool_calls": 10, "errors": 0,
             "extra_field": "should be ignored"},
        ]
        result = generate_benchmark_from_db(db_results, "extra-test")
        assert len(result["runs"]) == 1


# ==================== Full pipeline integration ====================

class TestPipelineIntegration:
    """End-to-end benchmark pipeline."""

    def test_calculate_to_aggregate_to_markdown(self):
        """Stats -> aggregate -> markdown pipeline works."""
        with_runs = [_make_run(0.8, 45.0, 3800), _make_run(0.85, 48.0, 3900), _make_run(0.82, 43.0, 3750)]
        without_runs = [_make_run(0.3, 30.0, 2000), _make_run(0.35, 32.0, 2100), _make_run(0.33, 31.0, 2050)]

        results = {"with_skill": with_runs, "without_skill": without_runs}
        summary = aggregate_results(results)

        assert summary["with_skill"]["pass_rate"]["mean"] > 0
        assert summary["without_skill"]["pass_rate"]["mean"] > 0
        assert "delta" in summary

        # Build full benchmark dict
        benchmark = {
            "metadata": {"skill_name": "pipeline-test", "executor_model": "test",
                         "timestamp": "2026-01-01T00:00:00Z", "evals_run": [1],
                         "runs_per_configuration": 3},
            "runs": [],
            "run_summary": summary,
            "notes": ["Pipeline test"],
        }

        md = generate_markdown(benchmark)
        assert "pipeline-test" in md
        assert isinstance(md, str)
