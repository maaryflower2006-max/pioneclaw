"""
Test benchmark_aggregator module (Phase 2c).

Tests: calculate_stats, aggregate_results, generate_benchmark_from_db,
and generate_markdown.
"""
import pytest

# ==================== calculate_stats ====================


class TestCalculateStats:
    """Tests for calculate_stats()."""

    def test_calculate_stats_basic(self):
        """Simple list of numbers — verify mean, stddev, min, max."""
        from app.services.skill_eval.benchmark_aggregator import calculate_stats

        stats = calculate_stats([2.0, 4.0, 6.0, 8.0])

        assert stats["mean"] == pytest.approx(5.0, rel=1e-3)
        assert stats["stddev"] == pytest.approx(2.582, rel=1e-3)
        assert stats["min"] == pytest.approx(2.0)
        assert stats["max"] == pytest.approx(8.0)

    def test_calculate_stats_single_value(self):
        """Single value — mean equals the value, stddev=0."""
        from app.services.skill_eval.benchmark_aggregator import calculate_stats

        stats = calculate_stats([3.5])

        assert stats["mean"] == pytest.approx(3.5)
        assert stats["stddev"] == pytest.approx(0.0)
        assert stats["min"] == pytest.approx(3.5)
        assert stats["max"] == pytest.approx(3.5)

    def test_calculate_stats_empty(self):
        """Empty list — all values should be 0.0."""
        from app.services.skill_eval.benchmark_aggregator import calculate_stats

        stats = calculate_stats([])

        assert stats["mean"] == 0.0
        assert stats["stddev"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0


# ==================== aggregate_results ====================


class TestAggregateResults:
    """Tests for aggregate_results()."""

    def test_aggregate_results_two_configs(self):
        """Two configs (with_skill / without_skill) — verify stats and delta."""
        from app.services.skill_eval.benchmark_aggregator import aggregate_results

        results = {
            "with_skill": [
                {
                    "eval_id": 0,
                    "run_number": 1,
                    "pass_rate": 0.85,
                    "passed": 17,
                    "failed": 3,
                    "total": 20,
                    "time_seconds": 12.5,
                    "tokens": 5000,
                    "tool_calls": 8,
                    "errors": 1,
                    "expectations": [{"text": "Test", "passed": True}],
                    "notes": [],
                },
                {
                    "eval_id": 0,
                    "run_number": 2,
                    "pass_rate": 0.90,
                    "passed": 18,
                    "failed": 2,
                    "total": 20,
                    "time_seconds": 11.0,
                    "tokens": 4800,
                    "tool_calls": 7,
                    "errors": 0,
                    "expectations": [{"text": "Test", "passed": True}],
                    "notes": [],
                },
                {
                    "eval_id": 0,
                    "run_number": 3,
                    "pass_rate": 0.80,
                    "passed": 16,
                    "failed": 4,
                    "total": 20,
                    "time_seconds": 13.0,
                    "tokens": 5200,
                    "tool_calls": 9,
                    "errors": 2,
                    "expectations": [{"text": "Test", "passed": True}],
                    "notes": [],
                },
            ],
            "without_skill": [
                {
                    "eval_id": 0,
                    "run_number": 1,
                    "pass_rate": 0.60,
                    "passed": 12,
                    "failed": 8,
                    "total": 20,
                    "time_seconds": 18.0,
                    "tokens": 7000,
                    "tool_calls": 12,
                    "errors": 3,
                    "expectations": [{"text": "Test", "passed": False}],
                    "notes": [],
                },
                {
                    "eval_id": 0,
                    "run_number": 2,
                    "pass_rate": 0.65,
                    "passed": 13,
                    "failed": 7,
                    "total": 20,
                    "time_seconds": 17.5,
                    "tokens": 6800,
                    "tool_calls": 11,
                    "errors": 2,
                    "expectations": [{"text": "Test", "passed": False}],
                    "notes": [],
                },
                {
                    "eval_id": 0,
                    "run_number": 3,
                    "pass_rate": 0.55,
                    "passed": 11,
                    "failed": 9,
                    "total": 20,
                    "time_seconds": 19.0,
                    "tokens": 7200,
                    "tool_calls": 13,
                    "errors": 4,
                    "expectations": [{"text": "Test", "passed": False}],
                    "notes": [],
                },
            ],
        }

        run_summary = aggregate_results(results)

        # Verify configs exist
        assert "with_skill" in run_summary
        assert "without_skill" in run_summary
        assert "delta" in run_summary

        # Verify pass_rate stats for with_skill
        ws_pr = run_summary["with_skill"]["pass_rate"]
        assert ws_pr["mean"] == pytest.approx(0.85, rel=1e-3)
        assert ws_pr["min"] == pytest.approx(0.80)
        assert ws_pr["max"] == pytest.approx(0.90)

        # Verify pass_rate stats for without_skill
        nos_pr = run_summary["without_skill"]["pass_rate"]
        assert nos_pr["mean"] == pytest.approx(0.60, rel=1e-3)
        assert nos_pr["min"] == pytest.approx(0.55)
        assert nos_pr["max"] == pytest.approx(0.65)

        # Delta: with_skill - without_skill = 0.85 - 0.60 = 0.25
        delta = run_summary["delta"]
        assert delta["pass_rate"] == "+0.25"

        # Verify time_seconds stats
        ws_time = run_summary["with_skill"]["time_seconds"]
        assert ws_time["mean"] == pytest.approx(12.166, rel=1e-2)

        # Verify tokens stats
        ws_tokens = run_summary["with_skill"]["tokens"]
        assert ws_tokens["mean"] == pytest.approx(5000.0, rel=1e-3)


# ==================== generate_benchmark_from_db ====================


class TestGenerateBenchmarkFromDB:
    """Tests for generate_benchmark_from_db()."""

    def test_generate_benchmark_from_db(self):
        """Sample DB results — verify benchmark dict structure."""
        from app.services.skill_eval.benchmark_aggregator import generate_benchmark_from_db

        results = [
            {
                "configuration": "with_skill",
                "eval_id": 1,
                "run_number": 1,
                "pass_rate": 0.92,
                "passed": 23,
                "failed": 2,
                "total": 25,
                "time_seconds": 10.0,
                "tokens": 4000,
                "tool_calls": 5,
                "errors": 0,
                "expectations": [{"text": "Do X", "passed": True}],
                "notes": ["all good"],
            },
            {
                "configuration": "with_skill",
                "eval_id": 1,
                "run_number": 2,
                "pass_rate": 0.88,
                "passed": 22,
                "failed": 3,
                "total": 25,
                "time_seconds": 11.0,
                "tokens": 4200,
                "tool_calls": 6,
                "errors": 1,
                "expectations": [{"text": "Do X", "passed": False}],
                "notes": ["minor issue"],
            },
            {
                "configuration": "without_skill",
                "eval_id": 1,
                "run_number": 1,
                "pass_rate": 0.65,
                "passed": 16,
                "failed": 9,
                "total": 25,
                "time_seconds": 18.0,
                "tokens": 6500,
                "tool_calls": 15,
                "errors": 4,
                "expectations": [{"text": "Do X", "passed": False}],
                "notes": ["struggled"],
            },
            {
                "configuration": "without_skill",
                "eval_id": 1,
                "run_number": 2,
                "pass_rate": 0.60,
                "passed": 15,
                "failed": 10,
                "total": 25,
                "time_seconds": 19.0,
                "tokens": 6700,
                "tool_calls": 14,
                "errors": 5,
                "expectations": [{"text": "Do X", "passed": False}],
                "notes": ["failed"],
            },
        ]

        skill_name = "my-test-skill"
        benchmark = generate_benchmark_from_db(results, skill_name)

        # Verify top-level keys
        assert "metadata" in benchmark
        assert "runs" in benchmark
        assert "run_summary" in benchmark
        assert "notes" in benchmark

        # Verify metadata
        meta = benchmark["metadata"]
        assert meta["skill_name"] == skill_name
        assert isinstance(meta["timestamp"], str)
        assert len(meta["timestamp"]) > 0
        assert meta["evals_run"] == [1]
        assert meta["runs_per_configuration"] == 2

        # Verify runs
        assert len(benchmark["runs"]) == 4  # 2 per config
        for run in benchmark["runs"]:
            assert "eval_id" in run
            assert "configuration" in run
            assert "run_number" in run
            assert "result" in run
            assert "expectations" in run
            assert "notes" in run

        # Verify run_summary
        run_summary = benchmark["run_summary"]
        assert "with_skill" in run_summary
        assert "without_skill" in run_summary
        assert "delta" in run_summary

        ws_pr = run_summary["with_skill"]["pass_rate"]
        assert ws_pr["mean"] == pytest.approx(0.90, rel=1e-3)

        nos_pr = run_summary["without_skill"]["pass_rate"]
        assert nos_pr["mean"] == pytest.approx(0.625, rel=1e-3)

        # Delta
        assert run_summary["delta"]["pass_rate"] == "+0.28"


# ==================== generate_markdown ====================


class TestGenerateMarkdown:
    """Tests for generate_markdown()."""

    def test_generate_markdown(self):
        """Benchmark dict — verify markdown string contains expected elements."""
        from app.services.skill_eval.benchmark_aggregator import generate_markdown

        benchmark = {
            "metadata": {
                "skill_name": "my-skill",
                "skill_path": "/path/to/skill",
                "executor_model": "claude-sonnet-4-6",
                "analyzer_model": "claude-sonnet-4-6",
                "timestamp": "2026-01-15T10:30:00Z",
                "evals_run": [0, 1],
                "runs_per_configuration": 3,
            },
            "runs": [],
            "run_summary": {
                "with_skill": {
                    "pass_rate": {"mean": 0.85, "stddev": 0.05, "min": 0.80, "max": 0.90},
                    "time_seconds": {"mean": 12.0, "stddev": 1.5, "min": 10.0, "max": 14.0},
                    "tokens": {"mean": 5000, "stddev": 200, "min": 4800, "max": 5200},
                },
                "without_skill": {
                    "pass_rate": {"mean": 0.60, "stddev": 0.10, "min": 0.50, "max": 0.70},
                    "time_seconds": {"mean": 18.0, "stddev": 2.0, "min": 16.0, "max": 20.0},
                    "tokens": {"mean": 7000, "stddev": 300, "min": 6700, "max": 7300},
                },
                "delta": {
                    "pass_rate": "+0.25",
                    "time_seconds": "-6.0",
                    "tokens": "-2000",
                },
            },
            "notes": ["Note 1: something", "Note 2: something else"],
        }

        md = generate_markdown(benchmark)

        # Verify key elements in the markdown
        assert "# Skill Benchmark: my-skill" in md
        assert "**Model**: claude-sonnet-4-6" in md
        assert "**Date**: 2026-01-15T10:30:00Z" in md
        assert "## Summary" in md
        assert "Pass Rate" in md
        assert "Time" in md
        assert "Tokens" in md
        assert "Delta" in md
        assert "+0.25" in md
        assert "-6.0" in md
        assert "-2000" in md
        assert "## Notes" in md
        assert "Note 1: something" in md
        assert "Note 2: something else" in md
