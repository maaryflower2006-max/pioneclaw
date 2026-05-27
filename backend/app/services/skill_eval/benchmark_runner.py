"""Benchmark runner --- tests skill effectiveness via with/without comparison.

Uses subagent tasks (spawned via httpx to the internal subagent API) to run
each test prompt with and without skill instructions, then grades outputs
using an LLM comparator.  Aggregates results into a BenchmarkResult dataclass.

Public API:
  - run(skill_content, test_prompts)   Spawns subagent tasks, polls, grades
                                       via LLM, returns BenchmarkResult.
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx

from app.modules.llm.provider import SimpleLLMProvider
from app.services.skill_eval.prompts.comparator_prompt import build_comparator_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses --- kept for backward compatibility with app.api.skill_eval
# ---------------------------------------------------------------------------

@dataclass
class RubricScore:
    content: float = 0.0    # 1-5
    structure: float = 0.0  # 1-5
    overall: float = 0.0    # 1-10


@dataclass
class BenchmarkRun:
    prompt: str
    with_skill_output: str = ""
    baseline_output: str = ""
    passed: bool = False
    reasoning: str = ""
    rubric: RubricScore = field(default_factory=RubricScore)
    # 断言式 grading 结果
    with_skill_assertions: list[dict] = field(default_factory=list)
    baseline_assertions: list[dict] = field(default_factory=list)
    with_skill_time: float = 0.0
    baseline_time: float = 0.0
    with_skill_tokens: int = 0
    baseline_tokens: int = 0


@dataclass
class BenchmarkResult:
    pass_rate: float = 0.0       # 0.0 - 1.0 (LLM comparator)
    delta: str = ""              # e.g. "+15%"
    runs: list[BenchmarkRun] = field(default_factory=list)
    summary: str = ""
    score: int = 0               # 0-100 mapped from pass_rate
    available: bool = True
    avg_rubric: RubricScore = field(default_factory=RubricScore)
    # 断言式 grading 统计
    assertion_total: int = 0
    assertion_with_passed: int = 0
    assertion_baseline_passed: int = 0
    # 结构化 stats（含 mean/stddev/delta）
    stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Subagent task status helper
# ---------------------------------------------------------------------------

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


# ---------------------------------------------------------------------------
# BenchmarkRunner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """Runs a skill against test prompts with/without skill injection using
    subagent tasks spawned via the internal subagent API, then grades outputs
    via an LLM comparator.

    Constructor:
        BenchmarkRunner(llm=provider)
        BenchmarkRunner(llm=provider, subagent_manager=manager)  # deprecated arg
        BenchmarkRunner(llm=provider, poll_timeout_seconds=300)
    """

    def __init__(
        self,
        llm: SimpleLLMProvider = None,
        subagent_manager=None,
        poll_timeout_seconds: float = 300.0,
        auth_token: str = "",
    ):
        self.llm = llm
        self.subagent_manager = subagent_manager   # kept for compat
        self.poll_timeout_seconds = poll_timeout_seconds
        self._base_url = os.getenv("SUBAGENT_API_URL", "http://localhost:8002/api")
        self._auth_headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        skill_content: str,
        test_prompts: list[dict],
    ) -> BenchmarkResult:
        """Run with/without skill comparison using subagent tasks via internal API.

        test_prompts: [{"prompt": str, "expected": str}]
        """
        # ── 0. Handle empty prompts ─────────────────────────────────────
        if not test_prompts:
            return BenchmarkResult(
                pass_rate=0.0,
                delta="N/A",
                runs=[],
                summary="No test prompts provided.",
                score=0,
                available=True,
            )

        # ── 1. Strip frontmatter from skill_content ─────────────────────
        skill_body = self._strip_frontmatter(skill_content)

        # ── 2. Spawn subagent tasks (2 per prompt) ──────────────────────
        #     tasks_meta: list of (prompt_index, config_name, task_id)
        tasks_meta: list[tuple[int, str, str]] = []

        for idx, tp in enumerate(test_prompts):
            prompt = tp.get("prompt", "")

            # with_skill: inject skill instructions as system_prompt (truncate to avoid overwhelming model)
            with_sys = f"<skill-instructions>\n{skill_body[:1500]}\n</skill-instructions>"
            tid_with = await self._spawn_subagent(
                message=f"Task: {prompt}",
                system_prompt=with_sys,
            )
            tasks_meta.append((idx, "with_skill", tid_with))

            # without_skill: empty system_prompt (no skill instructions)
            tid_without = await self._spawn_subagent(
                message=f"Task: {prompt}",
                system_prompt="",
            )
            tasks_meta.append((idx, "without_skill", tid_without))

        # ── 3. Poll all tasks until completion or timeout ───────────────
        task_results: dict[str, dict] = await self._poll_all_tasks(
            [t[2] for t in tasks_meta],
            timeout=self.poll_timeout_seconds,
        )

        # ── 4. Grade each prompt-pair: assertion grading + LLM comparator ──
        runs: list[BenchmarkRun] = []
        rubric_scores: list[RubricScore] = []
        passed_count = 0
        all_with_times: list[float] = []
        all_baseline_times: list[float] = []
        all_with_tokens: list[int] = []
        all_baseline_tokens: list[int] = []
        total_assertions = 0
        total_with_assertion_pass = 0
        total_baseline_assertion_pass = 0

        for idx, tp in enumerate(test_prompts):
            prompt = tp.get("prompt", "")
            expected = tp.get("expected", "")
            assertions = tp.get("assertions", [])

            with_tid = tasks_meta[idx * 2][2]
            without_tid = tasks_meta[idx * 2 + 1][2]

            with_result = task_results.get(with_tid, {})
            without_result = task_results.get(without_tid, {})

            with_output = with_result.get("result", "") or ""
            without_output = without_result.get("result", "") or ""
            with_time = float(with_result.get("duration", 0) or 0)
            baseline_time = float(without_result.get("duration", 0) or 0)
            with_tokens = int(with_result.get("tokens", 0) or 0)
            baseline_tokens = int(without_result.get("tokens", 0) or 0)

            # ── 4a. Assertion grading ───────────────────────────────
            with_assertions: list[dict] = []
            baseline_assertions: list[dict] = []
            if assertions:
                with_assertions, baseline_assertions = self._grade_assertions(
                    assertions, with_output, without_output
                )
                total_assertions += len(assertions)
                total_with_assertion_pass += sum(1 for a in with_assertions if a["passed"])
                total_baseline_assertion_pass += sum(1 for a in baseline_assertions if a["passed"])

            # ── 4b. LLM comparator grading ─────────────────────────
            try:
                passed, reasoning, rubric = await self._grade(
                    prompt, expected, with_output, without_output
                )
            except Exception as e:
                logger.error("Grading failed for prompt %d: %s", idx, e)
                passed = False
                reasoning = f"Grading error: {e}"
                rubric = None

            if passed:
                passed_count += 1
            if rubric:
                rubric_scores.append(rubric)
            if with_time:
                all_with_times.append(with_time)
            if baseline_time:
                all_baseline_times.append(baseline_time)
            if with_tokens:
                all_with_tokens.append(with_tokens)
            if baseline_tokens:
                all_baseline_tokens.append(baseline_tokens)

            runs.append(BenchmarkRun(
                prompt=prompt,
                with_skill_output=with_output,
                baseline_output=without_output,
                passed=passed,
                reasoning=reasoning,
                rubric=rubric or RubricScore(),
                with_skill_assertions=with_assertions,
                baseline_assertions=baseline_assertions,
                with_skill_time=with_time,
                baseline_time=baseline_time,
                with_skill_tokens=with_tokens,
                baseline_tokens=baseline_tokens,
            ))

        # ── 5. Aggregate results ────────────────────────────────────────
        total = len(runs)
        pass_rate = passed_count / total if total > 0 else 0.0
        score = int(pass_rate * 100)

        avg_rubric = RubricScore()
        if rubric_scores:
            avg_rubric = RubricScore(
                content=round(sum(r.content for r in rubric_scores) / len(rubric_scores), 1),
                structure=round(sum(r.structure for r in rubric_scores) / len(rubric_scores), 1),
                overall=round(sum(r.overall for r in rubric_scores) / len(rubric_scores), 1),
            )

        delta = f"{int((pass_rate - 0.5) * 100):+d}%"
        if pass_rate == 0.0:
            delta = "-50%"

        summary = f"Subagent comparison: {passed_count}/{total} prompts passed"
        if pass_rate >= 0.8:
            summary += " -- skill significantly improves output quality"
        elif pass_rate >= 0.5:
            summary += " -- skill provides moderate help"
        else:
            summary += " -- skill shows limited or negative effect"

        # ── 5b. Compute structured stats (mean/stddev for time, tokens, assertion pass-rate) ──
        stats = self._compute_benchmark_stats(
            runs, all_with_times, all_baseline_times,
            all_with_tokens, all_baseline_tokens,
        )

        return BenchmarkResult(
            pass_rate=pass_rate,
            delta=delta,
            runs=runs,
            summary=summary,
            score=score,
            available=True,
            avg_rubric=avg_rubric,
            assertion_total=total_assertions,
            assertion_with_passed=total_with_assertion_pass,
            assertion_baseline_passed=total_baseline_assertion_pass,
            stats=stats,
        )

    async def run_stream(self, skill_content: str, test_prompts: list[dict]):
        """Stream benchmark results as each prompt pair completes.

        Yields SSE-formatted strings:
          data: {"type":"progress","idx":0,"prompt":"...","status":"spawned"}
          data: {"type":"result","idx":0,"total":3,"run":{...}}
          data: {"type":"summary","pass_rate":...,"delta":...,...}

        Design:
        - Spawn ALL 2N tasks first in parallel (asyncio.gather)
        - Group task_ids into N pairs (with_skill, without_skill)
        - For each pair, create an asyncio.Task that polls both, grades, returns result
        - Use asyncio.as_completed() to yield results as each pair finishes
        - After all pairs complete, yield final aggregate summary
        """
        skill_body = self._strip_frontmatter(skill_content)

        # ── 0. Handle empty prompts ─────────────────────────────────────
        if not test_prompts:
            yield self._sse_event({
                "type": "summary",
                "pass_rate": 0.0,
                "delta": "N/A",
                "score": 0,
                "runs": [],
                "summary": "No test prompts provided.",
            })
            return

        # ── 1. Spawn ALL tasks in parallel ──────────────────────────────
        total_prompts = len(test_prompts)
        spawn_coroutines = []
        for idx, tp in enumerate(test_prompts):
            prompt = tp.get("prompt", "")
            # with_skill
            with_sys = f"<skill-instructions>\n{skill_body[:1500]}\n</skill-instructions>"
            spawn_coroutines.append(self._spawn_subagent(
                message=f"Task: {prompt}",
                system_prompt=with_sys,
            ))
            # without_skill
            spawn_coroutines.append(self._spawn_subagent(
                message=f"Task: {prompt}",
                system_prompt="",
            ))

        # Collect all task_ids
        all_task_ids = await asyncio.gather(*spawn_coroutines)

        # ── 2. Build pair-level async tasks ─────────────────────────────
        async def _process_pair(idx: int) -> tuple[list[str], BenchmarkRun]:
            events: list[str] = []
            with_tid = all_task_ids[idx * 2]
            without_tid = all_task_ids[idx * 2 + 1]
            prompt = test_prompts[idx].get("prompt", "")
            expected = test_prompts[idx].get("expected", "")
            assertions = test_prompts[idx].get("assertions", [])

            # Yield progress: tasks spawned
            events.append(self._sse_event({
                "type": "progress",
                "idx": idx,
                "total": total_prompts,
                "prompt": prompt,
                "status": "spawned",
            }))

            # Poll both tasks until completion or timeout
            pair_ids = [with_tid, without_tid]
            pair_results = await self._poll_all_tasks(
                pair_ids, timeout=self.poll_timeout_seconds,
            )

            # Yield progress: grading
            events.append(self._sse_event({
                "type": "progress",
                "idx": idx,
                "total": total_prompts,
                "prompt": prompt,
                "status": "grading",
            }))

            with_result = pair_results.get(with_tid, {})
            without_result = pair_results.get(without_tid, {})

            with_output = with_result.get("result", "") or ""
            without_output = without_result.get("result", "") or ""
            with_time = float(with_result.get("duration", 0) or 0)
            baseline_time = float(without_result.get("duration", 0) or 0)
            with_tokens = int(with_result.get("tokens", 0) or 0)
            baseline_tokens = int(without_result.get("tokens", 0) or 0)

            # If both tasks timed out with no output, skip grading
            if not with_output and not without_output:
                events.append(self._sse_event({
                    "type": "progress",
                    "idx": idx,
                    "total": total_prompts,
                    "prompt": prompt,
                    "status": "timeout",
                }))
                return events, BenchmarkRun(
                    prompt=prompt,
                    with_skill_output="",
                    baseline_output="",
                    passed=False,
                    reasoning="Both tasks timed out.",
                    rubric=RubricScore(),
                )

            # ── Assertion grading ──────────────────────────────────
            with_assertions: list[dict] = []
            baseline_assertions: list[dict] = []
            if assertions:
                with_assertions, baseline_assertions = self._grade_assertions(
                    assertions, with_output, without_output
                )

            # ── LLM comparator grading ─────────────────────────────
            try:
                passed, reasoning, rubric = await self._grade(
                    prompt, expected, with_output, without_output
                )
            except Exception as e:
                logger.error("Grading failed for prompt %d: %s", idx, e)
                passed = False
                reasoning = f"Grading error: {e}"
                rubric = None

            run = BenchmarkRun(
                prompt=prompt,
                with_skill_output=with_output,
                baseline_output=without_output,
                passed=passed,
                reasoning=reasoning,
                rubric=rubric or RubricScore(),
                with_skill_assertions=with_assertions,
                baseline_assertions=baseline_assertions,
                with_skill_time=with_time,
                baseline_time=baseline_time,
                with_skill_tokens=with_tokens,
                baseline_tokens=baseline_tokens,
            )

            # Yield result event
            events.append(self._sse_event({
                "type": "result",
                "idx": idx,
                "total": total_prompts,
                "run": {
                    "prompt": run.prompt,
                    "with_skill_output": run.with_skill_output[:500],
                    "baseline_output": run.baseline_output[:500],
                    "passed": run.passed,
                    "reasoning": run.reasoning[:200],
                    "rubric": {
                        "content": run.rubric.content,
                        "structure": run.rubric.structure,
                        "overall": run.rubric.overall,
                    },
                    "with_assertions": [
                        {"text": a["text"], "passed": a["passed"], "evidence": a["evidence"]}
                        for a in with_assertions
                    ],
                    "baseline_assertions": [
                        {"text": a["text"], "passed": a["passed"], "evidence": a["evidence"]}
                        for a in baseline_assertions
                    ],
                    "with_time": with_time,
                    "baseline_time": baseline_time,
                    "with_tokens": with_tokens,
                    "baseline_tokens": baseline_tokens,
                },
            }))

            return events, run

        # ── 3. Run pair tasks concurrently, yield as they complete ──────
        # Wrap each _process_pair call with its index for tracking
        async def _process_with_idx(idx: int):
            events, run = await _process_pair(idx)
            return idx, events, run

        tasks = [asyncio.ensure_future(_process_with_idx(i)) for i in range(total_prompts)]

        completed_runs: dict[int, BenchmarkRun] = {}
        for task in asyncio.as_completed(tasks):
            idx, events, run = await task
            completed_runs[idx] = run
            for evt in events:
                yield evt

        # Reorder runs by original index
        ordered_runs = [
            completed_runs[i]
            for i in range(total_prompts)
            if i in completed_runs
        ]

        # ── 4. Aggregate and yield summary ─────────────────────────────
        total = len(ordered_runs)
        passed_count = sum(1 for r in ordered_runs if r.passed)
        pass_rate = passed_count / total if total > 0 else 0.0
        score = int(pass_rate * 100)

        rubric_scores = [r.rubric for r in ordered_runs if r.rubric and r.rubric.overall > 0]
        avg_rubric = RubricScore()
        if rubric_scores:
            avg_rubric = RubricScore(
                content=round(sum(r.content for r in rubric_scores) / len(rubric_scores), 1),
                structure=round(sum(r.structure for r in rubric_scores) / len(rubric_scores), 1),
                overall=round(sum(r.overall for r in rubric_scores) / len(rubric_scores), 1),
            )

        delta = f"{int((pass_rate - 0.5) * 100):+d}%"
        if pass_rate == 0.0:
            delta = "-50%"

        summary = f"Subagent comparison: {passed_count}/{total} prompts passed"
        if pass_rate >= 0.8:
            summary += " -- skill significantly improves output quality"
        elif pass_rate >= 0.5:
            summary += " -- skill provides moderate help"
        else:
            summary += " -- skill shows limited or negative effect"

        # Structured stats
        all_with_times = [r.with_skill_time for r in ordered_runs if r.with_skill_time]
        all_baseline_times = [r.baseline_time for r in ordered_runs if r.baseline_time]
        all_with_tokens = [r.with_skill_tokens for r in ordered_runs if r.with_skill_tokens]
        all_baseline_tokens = [r.baseline_tokens for r in ordered_runs if r.baseline_tokens]
        stats = self._compute_benchmark_stats(
            ordered_runs, all_with_times, all_baseline_times,
            all_with_tokens, all_baseline_tokens,
        )

        assertion_total = sum(len(r.with_skill_assertions) for r in ordered_runs)
        assertion_with = sum(sum(1 for a in r.with_skill_assertions if a.get("passed")) for r in ordered_runs)
        assertion_baseline = sum(sum(1 for a in r.baseline_assertions if a.get("passed")) for r in ordered_runs)

        yield self._sse_event({
            "type": "summary",
            "pass_rate": round(pass_rate, 3),
            "delta": delta,
            "score": score,
            "summary": summary,
            "avg_rubric": {
                "content": avg_rubric.content,
                "structure": avg_rubric.structure,
                "overall": avg_rubric.overall,
            },
            "assertion_summary": {
                "total": assertion_total,
                "with_skill_passed": assertion_with,
                "baseline_passed": assertion_baseline,
            },
            "stats": stats,
            "runs": [
                {
                    "prompt": r.prompt,
                    "with_skill_output": r.with_skill_output[:500],
                    "baseline_output": r.baseline_output[:500],
                    "passed": r.passed,
                    "reasoning": r.reasoning[:200],
                    "rubric": {
                        "content": r.rubric.content,
                        "structure": r.rubric.structure,
                        "overall": r.rubric.overall,
                    },
                    "with_assertions": r.with_skill_assertions,
                    "baseline_assertions": r.baseline_assertions,
                    "with_time": r.with_skill_time,
                    "baseline_time": r.baseline_time,
                    "with_tokens": r.with_skill_tokens,
                    "baseline_tokens": r.baseline_tokens,
                }
                for r in ordered_runs
            ],
        })

    # ------------------------------------------------------------------
    # Stream helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sse_event(data: dict) -> str:
        """Format a dict as an SSE data string."""
        import json
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # ------------------------------------------------------------------
    # Subagent API helpers (overridable for testing)
    # ------------------------------------------------------------------

    async def _spawn_subagent(self, message: str, system_prompt: str = "") -> str:
        """Create and execute a subagent task via the internal subagent API.

        Returns the task_id string.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0, headers=self._auth_headers) as client:
            resp = await client.post("/subagent/tasks", json={
                "label": f"benchmark-{uuid4().hex[:8]}",
                "message": message,
                "system_prompt": system_prompt or "",
                "task_type": "general",
            })
            resp.raise_for_status()
            data = resp.json()
            return data["task_id"]

    async def _poll_task(self, task_id: str) -> dict:
        """Poll a single subagent task status.

        Returns dict with keys: status, result, error, duration.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0, headers=self._auth_headers) as client:
            resp = await client.get(f"/subagent/tasks/{task_id}")
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status", "pending")
            result = data.get("result", "") or ""
            error = data.get("error", "") or ""

            # Compute duration from timestamps if available
            duration = 0.0
            started = data.get("started_at")
            completed = data.get("completed_at")
            if started and completed:
                try:
                    from datetime import datetime as dt
                    s = dt.fromisoformat(started.replace("Z", "+00:00"))
                    c = dt.fromisoformat(completed.replace("Z", "+00:00"))
                    duration = (c - s).total_seconds()
                except (ValueError, TypeError):
                    pass

            return {
                "status": status,
                "result": result,
                "error": error,
                "duration": duration,
            }

    async def _poll_all_tasks(
        self, task_ids: list[str], timeout: float = 300.0,
    ) -> dict[str, dict]:
        """Poll multiple tasks until all complete or timeout expires.

        Returns a dict mapping task_id -> poll result dict.
        """
        pending: set[str] = set(task_ids)
        results: dict[str, dict] = {}
        start = time.monotonic()

        while pending and (time.monotonic() - start < timeout):
            for tid in list(pending):
                try:
                    task = await self._poll_task(tid)
                except Exception as e:
                    logger.warning("Poll failed for task %s: %s", tid, e)
                    # Treat poll failure as transient; keep polling
                    continue

                if task["status"] in TERMINAL_STATUSES:
                    results[tid] = task
                    pending.discard(tid)

            if pending:
                await asyncio.sleep(2.0)

        # Mark remaining as timeouts
        for tid in pending:
            results[tid] = {
                "status": "timeout",
                "result": "",
                "error": f"Polling timed out after {timeout}s",
                "duration": 0.0,
            }

        return results

    # ------------------------------------------------------------------
    # Frontmatter stripping
    # ------------------------------------------------------------------

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter (delimited by ---) from skill content."""
        if not content:
            return ""
        if content.startswith("---"):
            match = re.match(r"^---[\r\n]+.*?[\r\n]+---[\r\n]*", content, re.DOTALL)
            if match:
                return content[match.end():]
        return content

    # ------------------------------------------------------------------
    # Assertion grading
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_stats(values: list[float]) -> dict:
        """计算 mean, stddev, min, max。"""
        if not values:
            return {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0}
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n if n > 1 else 0.0
        return {
            "mean": round(mean, 2),
            "stddev": round(variance ** 0.5, 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    @staticmethod
    def _compute_benchmark_stats(
        runs: list,
        with_times: list[float],
        baseline_times: list[float],
        with_tokens: list[int],
        baseline_tokens: list[int],
    ) -> dict:
        """从 runs 中计算 with_skill / without_skill 的结构化统计。"""
        # Assertion pass rates per run
        with_assertion_rates: list[float] = []
        baseline_assertion_rates: list[float] = []
        for r in runs:
            wa = r.with_skill_assertions
            ba = r.baseline_assertions
            if wa:
                with_assertion_rates.append(sum(1 for a in wa if a.get("passed")) / len(wa))
            if ba:
                baseline_assertion_rates.append(sum(1 for a in ba if a.get("passed")) / len(ba))

        def _fmt_delta(w_stats: dict, b_stats: dict, suffix: str = "") -> str:
            diff = w_stats["mean"] - b_stats["mean"]
            return f"{diff:+.1f}{suffix}"

        stats = {
            "with_skill": {
                "assertion_pass_rate": BenchmarkRunner._compute_stats(with_assertion_rates),
                "time_seconds": BenchmarkRunner._compute_stats(with_times),
                "tokens": BenchmarkRunner._compute_stats([float(t) for t in with_tokens]),
            },
            "without_skill": {
                "assertion_pass_rate": BenchmarkRunner._compute_stats(baseline_assertion_rates),
                "time_seconds": BenchmarkRunner._compute_stats(baseline_times),
                "tokens": BenchmarkRunner._compute_stats([float(t) for t in baseline_tokens]),
            },
        }
        stats["delta"] = {
            "assertion_pass_rate": _fmt_delta(
                stats["with_skill"]["assertion_pass_rate"],
                stats["without_skill"]["assertion_pass_rate"],
            ),
            "time_seconds": _fmt_delta(
                stats["with_skill"]["time_seconds"],
                stats["without_skill"]["time_seconds"],
                "s",
            ),
            "tokens": _fmt_delta(
                stats["with_skill"]["tokens"],
                stats["without_skill"]["tokens"],
            ),
        }
        return stats

    def _grade_assertions(
        self,
        assertions: list[dict],
        with_output: str,
        baseline_output: str,
    ) -> tuple[list[dict], list[dict]]:
        """对 with_skill 和 baseline 输出分别按断言列表做 keyword grading。

        每条 assertion dict 格式：{"text": str, "description": str (可选)}
        返回两组 [{text, passed, evidence}, ...]。
        """
        with_results: list[dict] = []
        baseline_results: list[dict] = []

        for a in assertions:
            text = a.get("text", a.get("name", ""))
            desc = a.get("description", "")
            keywords = text.split()
            if not keywords:
                keywords = [text]

            # 关键词匹配：至少一个关键词出现在输出中
            w_passed = any(kw in with_output for kw in keywords if len(kw) >= 2)
            b_passed = any(kw in baseline_output for kw in keywords if len(kw) >= 2)

            with_results.append({
                "text": text,
                "description": desc,
                "passed": w_passed,
                "evidence": "Keyword(s) found in with_skill output" if w_passed else f"No keyword match for: {text}",
            })
            baseline_results.append({
                "text": text,
                "description": desc,
                "passed": b_passed,
                "evidence": "Keyword(s) found in baseline output" if b_passed else f"No keyword match for: {text}",
            })

        return with_results, baseline_results

    # ------------------------------------------------------------------
    # LLM grading
    # ------------------------------------------------------------------

    async def _grade(
        self,
        prompt: str,
        expected: str,
        with_output: str,
        baseline_output: str,
    ) -> tuple[bool, str, RubricScore | None]:
        """Use LLM comparator to blindly grade with_skill (A) vs baseline (B).

        Returns (passed, reasoning, rubric) where passed means A (with_skill) won.
        """
        # Build the comparator prompt (A = with_skill, B = baseline)
        comparator_prompt = build_comparator_prompt(
            output_a=with_output,
            output_b=baseline_output,
            eval_prompt=prompt,
            expectations=[expected] if expected else None,
        )

        messages = [
            {
                "role": "system",
                "content": "You are a strict quality judge. Output only JSON, no explanation.",
            },
            {"role": "user", "content": comparator_prompt},
        ]

        parts: list[str] = []
        try:
            async for chunk in self.llm.chat_stream(
                messages=messages, temperature=0.1, max_tokens=1200,
            ):
                if "error" in chunk:
                    raise RuntimeError(f"Comparator LLM error: {chunk['error']}")
                parts.append(chunk.get("content", ""))
        except Exception as e:
            raise RuntimeError(f"LLM grading call failed: {e}")

        raw = "".join(parts).strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
            winner = data.get("winner", "TIE")
            reasoning = str(data.get("reasoning", ""))[:200]

            rubric_data = data.get("rubric", {})
            a_rubric = rubric_data.get("A", {})

            passed = winner == "A"

            rubric = RubricScore(
                content=float(a_rubric.get("content_score", 0)),
                structure=float(a_rubric.get("structure_score", 0)),
                overall=float(a_rubric.get("overall_score", 0)),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            # Try regex recovery from truncated JSON
            match = re.search(r'"winner"\s*:\s*"([ABTIE]+)"', raw)
            passed = (match.group(1) if match else "TIE") == "A"
            r_match = re.search(r'"reasoning"\s*:\s*"([^"]{1,200})"', raw)
            reasoning = r_match.group(1) if r_match else f"JSON parse failed, raw: {raw[:80]}"
            rubric = None

        return passed, reasoning, rubric
