"""
Tests for BenchmarkRunner -- with-skill vs without-skill comparison via subagents.

Ten mock-based tests covering: task spawning per prompt, system_prompt injection,
polling loop, result collection, LLM grading, aggregation, timeout handling,
empty prompts, and skill-not-found edge cases.

Uses httpx-based subagent API calls (spawn + poll), with helpers mocked in tests.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.skill_eval.benchmark_runner import (
    BenchmarkResult,
    BenchmarkRunner,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SKILL_CONTENT = """---
name: test-skill
description: A test skill for benchmarking
---

# Test Skill

## Workflow
1. Read input
2. Process data
3. Output result

## Examples
- Input: "hello" -> Output: "HELLO"
"""

SKILL_BODY_ONLY = """# Test Skill

## Workflow
1. Read input
2. Process data
3. Output result

## Examples
- Input: "hello" -> Output: "HELLO"
"""

TEST_PROMPTS_DICT = [
    {"prompt": "Write a Python function for Fibonacci", "expected": "A working function"},
    {"prompt": "Explain machine learning", "expected": "Clear explanation"},
    {"prompt": "How do I write a for loop in JavaScript?", "expected": "Code example"},
]

TEST_PROMPTS_STR = [
    "Write a Python function for Fibonacci",
    "Explain machine learning",
    "How do I write a for loop in JavaScript?",
]


def make_comparison_json(winner="A", a_score=8.0, b_score=6.0):
    """Build a realistic comparison JSON response from the LLM comparator."""
    return {
        "winner": winner,
        "reasoning": f"Output {winner} was better structured and more complete.",
        "rubric": {
            "A": {
                "correctness": 4, "completeness": 5, "accuracy": 4,
                "organization": 4, "formatting": 4, "usability": 4,
                "content_score": 4.3, "structure_score": 4.0, "overall_score": a_score,
            },
            "B": {
                "correctness": 3, "completeness": 3, "accuracy": 3,
                "organization": 3, "formatting": 3, "usability": 3,
                "content_score": 3.0, "structure_score": 3.0, "overall_score": b_score,
            },
        },
        "output_quality": {
            "A": {"score": int(a_score), "strengths": ["Complete"], "weaknesses": ["Minor"]},
            "B": {"score": int(b_score), "strengths": ["Basic"], "weaknesses": ["Incomplete"]},
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_llm(comparison_data=None):
    """Create a mock SimpleLLMProvider whose chat_stream yields comparison JSON."""
    if comparison_data is None:
        comparison_data = make_comparison_json()

    async def _fake_stream(messages=None, temperature=0.1, max_tokens=1200):
        yield {"content": json.dumps(comparison_data)}

    llm = MagicMock()
    llm.chat_stream = _fake_stream
    llm.model = "test-model"
    return llm


def _make_spawn_mock(base_task_id=0):
    """Create a mock for _spawn_subagent that returns incrementing task IDs."""
    counter = [base_task_id]

    async def _spawn(message, system_prompt):
        tid = f"task-{counter[0]}"
        counter[0] += 1
        return tid

    return _spawn


def _make_poll_mock(task_outputs_by_config=None):
    """Create a mock for _poll_task that returns completed results.

    task_outputs_by_config is a dict mapping task_id prefix/pattern to output text.
    If not provided, generates default output based on task_id.
    """
    if task_outputs_by_config is None:
        task_outputs_by_config = {}

    async def _poll(task_id):
        output = task_outputs_by_config.get(task_id, f"Output from {task_id}")
        return {
            "status": "completed",
            "result": output,
            "error": None,
            "duration": 2.5,
        }

    return _poll


# ---------------------------------------------------------------------------
# Test Class
# ---------------------------------------------------------------------------

class TestBenchmarkRunnerSkillCreator:
    """Unit tests for BenchmarkRunner using mocked _spawn_subagent and _poll_task."""

    # ── Test 1: spawns two tasks per prompt ──────────────────────────────

    @pytest.mark.asyncio
    async def test_spawns_two_tasks_per_prompt(self):
        """3 prompts -> 6 subagent task spawns (3 with skill, 3 without)."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        spawn_counter = [0]

        async def mock_spawn(message, system_prompt):
            spawn_counter[0] += 1
            return f"task-{spawn_counter[0]}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Result from {task_id}", "duration": 1.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            result = await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        assert spawn_counter[0] == 6, (
            f"Expected 6 spawns (3 prompts * 2 configs), got {spawn_counter[0]}"
        )
        assert isinstance(result, BenchmarkResult)
        assert len(result.runs) == 3  # one BenchmarkRun per prompt

    # ── Test 2: with-skill tasks have skill instructions in system_prompt ──

    @pytest.mark.asyncio
    async def test_with_skill_has_skill_instructions_in_system_prompt(self):
        """with-skill spawns must include skill body in system_prompt."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        spawn_records = []

        async def mock_spawn(message, system_prompt):
            spawn_records.append({"message": message, "system_prompt": system_prompt})
            return f"task-{len(spawn_records)}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Result from {task_id}", "duration": 1.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        # First 3 spawns are with_skill (indices 0, 1, 2), last 3 are without
        with_skill_calls = spawn_records[0::2]  # indices 0, 2, 4
        without_skill_calls = spawn_records[1::2]  # indices 1, 3, 5

        assert len(with_skill_calls) == 3
        assert len(without_skill_calls) == 3

        # Every with_skill call must have the skill body in system_prompt
        for call in with_skill_calls:
            sp = call["system_prompt"]
            assert "<skill-instructions>" in sp, (
                f"Expected <skill-instructions> tag in system_prompt, got: {sp[:100]}"
            )
            assert "Workflow" in sp or "Process" in sp, (
                f"Expected skill body in system_prompt, got: {sp[:100]}"
            )

    # ── Test 3: without-skill tasks have empty system_prompt ─────────────

    @pytest.mark.asyncio
    async def test_without_skill_has_empty_system_prompt(self):
        """without-skill spawns must have empty or no system_prompt."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        spawn_records = []

        async def mock_spawn(message, system_prompt):
            spawn_records.append({"message": message, "system_prompt": system_prompt})
            return f"task-{len(spawn_records)}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Result from {task_id}", "duration": 1.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        without_skill_calls = spawn_records[1::2]  # indices 1, 3, 5

        assert len(without_skill_calls) == 3
        for call in without_skill_calls:
            sp = call.get("system_prompt", "")
            # Should be empty or blank (no skill instructions)
            assert "<skill-instructions>" not in sp, (
                f"without-skill should NOT have skill instructions, got: {sp[:100]}"
            )

    # ── Test 4: polls until all completed ────────────────────────────────

    @pytest.mark.asyncio
    async def test_polls_until_all_completed(self):
        """Runner polls all spawned tasks; polling loop completes when all done."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        spawn_count = [0]

        async def mock_spawn(message, system_prompt):
            spawn_count[0] += 1
            return f"task-{spawn_count[0]}"

        poll_call_count = [0]
        # First 5 polls return "running", then "completed"
        async def mock_poll(task_id):
            poll_call_count[0] += 1
            if poll_call_count[0] <= 5:
                return {"status": "running", "result": None, "error": None}
            return {"status": "completed", "result": f"Result from {task_id}", "duration": 1.0}

        # Mock sleep to be instantaneous and count calls
        sleep_count = [0]
        async def fake_sleep(seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= 3:
                # After 3rd sleep, make all further polls return completed
                poll_call_count[0] = 999  # Force all remaining polls to return completed

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll), \
             patch.object(asyncio, 'sleep', side_effect=fake_sleep):
            result = await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        assert sleep_count[0] >= 1, "Polling should invoke asyncio.sleep at least once"
        assert isinstance(result, BenchmarkResult)

    # ── Test 5: collects result text and timing ──────────────────────────

    @pytest.mark.asyncio
    async def test_collects_result_text_and_timing(self):
        """Completed tasks must have their output text collected in BenchmarkRun."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        spawn_count = [0]

        async def mock_spawn(message, system_prompt):
            spawn_count[0] += 1
            return f"task-{spawn_count[0]}"

        poll_results = {
            "task-1": {"status": "completed", "result": "Fibonacci with-skill output", "duration": 3.1},
            "task-2": {"status": "completed", "result": "Fibonacci baseline output", "duration": 2.2},
            "task-3": {"status": "completed", "result": "ML with-skill output", "duration": 4.0},
            "task-4": {"status": "completed", "result": "ML baseline output", "duration": 3.5},
            "task-5": {"status": "completed", "result": "JS with-skill output", "duration": 1.8},
            "task-6": {"status": "completed", "result": "JS baseline output", "duration": 2.0},
        }

        async def mock_poll(task_id):
            return poll_results.get(task_id, {"status": "completed", "result": f"Result {task_id}", "duration": 0})

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            result = await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        # Verify output text is collected
        assert len(result.runs) == 3
        assert "Fibonacci with-skill output" in result.runs[0].with_skill_output
        assert "Fibonacci baseline output" in result.runs[0].baseline_output

    # ── Test 6: grades each pair with comparator prompt ──────────────────

    @pytest.mark.asyncio
    async def test_grades_each_pair_with_comparator_prompt(self):
        """For N prompts, the LLM comparator should be invoked N times."""
        # Count LLM calls
        call_count = [0]
        comparison = make_comparison_json(winner="A", a_score=9.0, b_score=5.0)

        async def _counting_stream(messages=None, temperature=0.1, max_tokens=1200):
            call_count[0] += 1
            yield {"content": json.dumps(comparison)}

        llm = MagicMock()
        llm.chat_stream = _counting_stream
        llm.model = "test-model"
        runner = BenchmarkRunner(llm=llm)

        spawn_count = [0]

        async def mock_spawn(message, system_prompt):
            spawn_count[0] += 1
            return f"task-{spawn_count[0]}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Result from {task_id}", "duration": 1.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        assert call_count[0] == 3, (
            f"Expected 3 LLM grading calls (one per prompt), got {call_count[0]}"
        )

    # ── Test 7: aggregates into BenchmarkResult with delta/mean/stddev ───

    @pytest.mark.asyncio
    async def test_aggregates_into_benchmark_result(self):
        """Output must be a valid BenchmarkResult with correct pass_rate and delta."""
        # Use varying scores to test aggregation
        scores = [
            make_comparison_json(winner="A", a_score=8.5, b_score=4.0),
            make_comparison_json(winner="A", a_score=9.0, b_score=6.0),
            make_comparison_json(winner="B", a_score=5.0, b_score=7.0),  # B wins this one
        ]
        call_idx = [0]

        async def _counting_stream(messages=None, temperature=0.1, max_tokens=1200):
            data = scores[call_idx[0]]
            call_idx[0] += 1
            yield {"content": json.dumps(data)}

        llm = MagicMock()
        llm.chat_stream = _counting_stream
        llm.model = "test-model"
        runner = BenchmarkRunner(llm=llm)

        spawn_count = [0]

        async def mock_spawn(message, system_prompt):
            spawn_count[0] += 1
            return f"task-{spawn_count[0]}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"High quality result from {task_id}", "duration": 2.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            result = await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        # 2 out of 3 passed
        assert isinstance(result, BenchmarkResult)
        assert result.pass_rate == pytest.approx(2 / 3, abs=0.01)
        assert result.score == 66  # int(2/3 * 100) = 66
        assert len(result.runs) == 3

        # First two runs should pass (A wins), third should fail (B wins)
        assert result.runs[0].passed is True
        assert result.runs[1].passed is True
        assert result.runs[2].passed is False

        # avg_rubric should have values
        assert result.avg_rubric.overall > 0

    # ── Test 8: partial results on timeout ───────────────────────────────

    @pytest.mark.asyncio
    async def test_partial_results_on_timeout(self):
        """Tasks that never complete within timeout produce partial results."""
        fail_comparison = make_comparison_json(winner="B", a_score=0.0, b_score=5.0)  # B wins = with-skill lost

        async def _stream(messages=None, temperature=0.1, max_tokens=1200):
            yield {"content": json.dumps(fail_comparison)}

        llm = MagicMock()
        llm.chat_stream = _stream
        llm.model = "test-model"
        # Use a very short timeout for testing
        runner = BenchmarkRunner(llm=llm, poll_timeout_seconds=0.01)

        spawn_count = [0]

        async def mock_spawn(message, system_prompt):
            spawn_count[0] += 1
            return f"task-{spawn_count[0]}"

        # All polls return "running" -- tasks never complete
        async def mock_poll(task_id):
            return {"status": "running", "result": None, "error": None}

        # Make sleep instant
        async def fake_sleep(seconds):
            pass

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll), \
             patch.object(asyncio, 'sleep', side_effect=fake_sleep):
            result = await runner.run(SKILL_CONTENT, TEST_PROMPTS_DICT)

        # Should still return a BenchmarkResult, not crash
        assert isinstance(result, BenchmarkResult)
        # All tasks timed out -- should have empty outputs
        assert len(result.runs) == 3
        # With no outputs, grading likely fails for all -- but shouldn't crash
        assert result.pass_rate == 0.0

    # ── Test 9: empty prompts returns gracefully ─────────────────────────

    @pytest.mark.asyncio
    async def test_empty_prompts_returns_gracefully(self):
        """Empty test_prompts list should return BenchmarkResult with zero runs."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        spawn_called = [False]

        async def mock_spawn(message, system_prompt):
            spawn_called[0] = True
            return "should-not-be-called"

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn):
            result = await runner.run(SKILL_CONTENT, [])

        assert isinstance(result, BenchmarkResult)
        assert len(result.runs) == 0
        assert result.pass_rate == 0.0
        assert not spawn_called[0], "Should not spawn any tasks for empty prompts"

    # ── Test 10: skill not found handles gracefully ──────────────────────

    @pytest.mark.asyncio
    async def test_skill_not_found_handles_gracefully(self):
        """Empty skill content should still work (no skill instructions injected)."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        spawn_records = []

        async def mock_spawn(message, system_prompt):
            spawn_records.append({"message": message, "system_prompt": system_prompt})
            return f"task-{len(spawn_records)}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Result from {task_id}", "duration": 1.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            result = await runner.run("", TEST_PROMPTS_DICT)

        # Should run without crash; with_skill has empty instructions
        assert isinstance(result, BenchmarkResult)
        assert len(result.runs) == 3

        # With-skill tasks should still have the <skill-instructions> wrapper, just empty body
        with_skill_calls = spawn_records[0::2]
        for call in with_skill_calls:
            sp = call.get("system_prompt", "")
            assert "<skill-instructions>" in sp, (
                "system_prompt should still have <skill-instructions> tag"
            )

    # ── Test 11: strip_frontmatter removes YAML frontmatter ──────────────

    def test_strip_frontmatter_removes_yaml_frontmatter(self):
        """_strip_frontmatter should remove the --- delimited YAML block."""
        runner = BenchmarkRunner(llm=_make_mock_llm())

        result = runner._strip_frontmatter(SKILL_CONTENT)
        assert "---" not in result, f"Frontmatter should be stripped: {result[:100]}"
        assert "Workflow" in result, "Body content should be preserved"
        assert "name:" not in result, "YAML frontmatter keys should be removed"

    def test_strip_frontmatter_no_frontmatter(self):
        """Content without frontmatter should be returned as-is."""
        runner = BenchmarkRunner(llm=_make_mock_llm())

        plain_content = "# Just a heading\n\nSome body text."
        result = runner._strip_frontmatter(plain_content)
        assert result == plain_content


# ---------------------------------------------------------------------------
# TestBenchmarkStream -- streaming benchmark via SSE async generator
# ---------------------------------------------------------------------------


class TestBenchmarkStream:
    """Unit tests for BenchmarkRunner.run_stream() SSE async generator."""

    @pytest.mark.asyncio
    async def test_stream_yields_progress_events(self):
        """Each completed prompt pair yields an SSE progress + result event."""
        comparison = make_comparison_json(winner="A", a_score=8.0, b_score=5.0)

        async def _counting_stream(messages=None, temperature=0.1, max_tokens=1200):
            yield {"content": json.dumps(comparison)}

        llm = MagicMock()
        llm.chat_stream = _counting_stream
        llm.model = "test-model"

        runner = BenchmarkRunner(llm=llm)

        spawn_counter = [0]

        async def mock_spawn(message, system_prompt):
            spawn_counter[0] += 1
            return f"task-{spawn_counter[0]}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Output from {task_id}", "duration": 2.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            events = []
            async for sse_str in runner.run_stream(SKILL_CONTENT, TEST_PROMPTS_DICT):
                events.append(sse_str)

        # We should have at least progress + result + summary events
        assert len(events) >= 4, f"Expected >=4 SSE events, got {len(events)}"

        # Parse each SSE line to verify format
        parsed_events = []
        for sse_str in events:
            assert sse_str.startswith("data: "), f"SSE must start with 'data: ': {sse_str[:80]}"
            payload_str = sse_str[len("data: "):].strip()
            payload = json.loads(payload_str)
            assert "type" in payload, f"SSE event missing 'type': {payload}"
            parsed_events.append(payload)

        # Verify at least one "result" event per prompt
        result_events = [e for e in parsed_events if e["type"] == "result"]
        assert len(result_events) == 3, (
            f"Expected 3 result events, got {len(result_events)}"
        )

        # Verify a summary event exists
        summary_events = [e for e in parsed_events if e["type"] == "summary"]
        assert len(summary_events) == 1, (
            f"Expected 1 summary event, got {len(summary_events)}"
        )

        # Each result should have "run" with required fields
        for evt in result_events:
            run = evt.get("run", {})
            assert "prompt" in run
            assert "passed" in run
            assert "with_skill_output" in run
            assert "baseline_output" in run

    @pytest.mark.asyncio
    async def test_stream_yields_final_summary(self):
        """After all prompt pairs complete, yields a final aggregate summary."""
        comparison = make_comparison_json(winner="A", a_score=8.5, b_score=4.0)

        async def _stream(messages=None, temperature=0.1, max_tokens=1200):
            yield {"content": json.dumps(comparison)}

        llm = MagicMock()
        llm.chat_stream = _stream
        llm.model = "test-model"

        runner = BenchmarkRunner(llm=llm)

        spawn_counter = [0]

        async def mock_spawn(message, system_prompt):
            spawn_counter[0] += 1
            return f"task-{spawn_counter[0]}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Result {task_id}", "duration": 2.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            events = []
            async for sse_str in runner.run_stream(SKILL_CONTENT, TEST_PROMPTS_DICT):
                events.append(sse_str)

        # Last event should be the summary
        last = events[-1]
        payload = json.loads(last[len("data: "):].strip())
        assert payload["type"] == "summary", f"Last event should be summary, got: {payload.get('type')}"

        summary = payload
        assert "pass_rate" in summary, f"Summary missing pass_rate: {summary}"
        assert "delta" in summary, f"Summary missing delta: {summary}"
        assert "score" in summary, f"Summary missing score: {summary}"
        assert isinstance(summary["pass_rate"], (int, float))
        assert summary["pass_rate"] == pytest.approx(1.0, abs=0.01), (
            f"All A wins => pass_rate 1.0, got {summary['pass_rate']}"
        )

    @pytest.mark.asyncio
    async def test_stream_handles_empty_prompts(self):
        """Empty test_prompts list yields an immediate summary with zero runs."""
        llm = _make_mock_llm()
        runner = BenchmarkRunner(llm=llm)

        events = []
        async for sse_str in runner.run_stream(SKILL_CONTENT, []):
            events.append(sse_str)

        # Should yield exactly one summary event
        assert len(events) == 1, f"Expected 1 event for empty prompts, got {len(events)}"

        payload = json.loads(events[0][len("data: "):].strip())
        assert payload["type"] == "summary", f"Expected summary, got: {payload.get('type')}"
        assert payload["pass_rate"] == 0.0
        assert payload["delta"] == "N/A"
        assert payload.get("runs") == []

    @pytest.mark.asyncio
    async def test_stream_respects_timeout(self):
        """Partial completion still yields results for finished pairs."""
        fail_comparison = make_comparison_json(winner="B", a_score=3.0, b_score=8.0)

        async def _stream(messages=None, temperature=0.1, max_tokens=1200):
            yield {"content": json.dumps(fail_comparison)}

        llm = MagicMock()
        llm.chat_stream = _stream
        llm.model = "test-model"

        # Short timeout so polling expires quickly
        runner = BenchmarkRunner(llm=llm, poll_timeout_seconds=0.01)

        spawn_counter = [0]

        async def mock_spawn(message, system_prompt):
            spawn_counter[0] += 1
            return f"task-{spawn_counter[0]}"

        poll_call_counts: dict[str, int] = {}

        async def mock_poll(task_id):
            poll_call_counts[task_id] = poll_call_counts.get(task_id, 0) + 1
            # task-1 and task-2 complete immediately (first pair)
            if task_id in ("task-1", "task-2"):
                return {"status": "completed", "result": f"Quick result from {task_id}", "duration": 0.5}
            # Others never complete
            return {"status": "running", "result": None, "error": None}

        # Make sleep instant
        async def fake_sleep(seconds):
            pass

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll), \
             patch.object(asyncio, 'sleep', side_effect=fake_sleep):
            events = []
            async for sse_str in runner.run_stream(SKILL_CONTENT, TEST_PROMPTS_DICT):
                events.append(sse_str)

        # Should have: summary event at least (even if all timed out)
        parsed = [json.loads(e[len("data: "):].strip()) for e in events]
        summary_events = [e for e in parsed if e["type"] == "summary"]
        assert len(summary_events) == 1, (
            f"Should always get a summary event, got types: {[e['type'] for e in parsed]}"
        )

        # Since only first pair completed, we should get at most 1 result
        result_events = [e for e in parsed if e["type"] == "result"]
        assert len(result_events) <= 1, (
            f"Expected at most 1 result (only first pair finished), got {len(result_events)}"
        )

    @pytest.mark.asyncio
    async def test_stream_event_format(self):
        """Each SSE event must have type/data fields with valid JSON payload."""
        comparison = make_comparison_json(winner="A", a_score=9.0, b_score=6.0)

        async def _stream(messages=None, temperature=0.1, max_tokens=1200):
            yield {"content": json.dumps(comparison)}

        llm = MagicMock()
        llm.chat_stream = _stream
        llm.model = "test-model"

        runner = BenchmarkRunner(llm=llm)

        spawn_counter = [0]

        async def mock_spawn(message, system_prompt):
            spawn_counter[0] += 1
            return f"task-{spawn_counter[0]}"

        async def mock_poll(task_id):
            return {"status": "completed", "result": f"Output from {task_id}", "duration": 1.0}

        with patch.object(runner, '_spawn_subagent', side_effect=mock_spawn), \
             patch.object(runner, '_poll_task', side_effect=mock_poll):
            events = []
            async for sse_str in runner.run_stream(SKILL_CONTENT, TEST_PROMPTS_DICT):
                events.append(sse_str)

        valid_types = {"progress", "result", "summary"}

        for sse_str in events:
            # Must start with "data: "
            assert sse_str.startswith("data: "), (
                f"SSE line must start with 'data: ', got: {sse_str[:60]}"
            )
            assert sse_str.endswith("\n\n"), (
                f"SSE line must end with double newline, got: {repr(sse_str[-10:])}"
            )

            # Parse the JSON payload
            payload_str = sse_str[len("data: "):-2]  # strip "data: " and "\n\n"
            payload = json.loads(payload_str)
            assert "type" in payload, f"Missing 'type' in: {payload}"
            assert payload["type"] in valid_types, (
                f"Invalid type '{payload['type']}', expected one of {valid_types}"
            )

            # Progress events have idx, prompt, status
            if payload["type"] == "progress":
                assert "idx" in payload
                assert "prompt" in payload
                assert "status" in payload

            # Result events have run data
            if payload["type"] == "result":
                assert "run" in payload
                run = payload["run"]
                assert "prompt" in run
                assert "passed" in run
                assert isinstance(run["passed"], bool)

            # Summary events have aggregate data
            if payload["type"] == "summary":
                assert "pass_rate" in payload
                assert "delta" in payload
                assert "score" in payload
                assert "runs" in payload
