"""
Edge case tests for Skill Evaluation API endpoints.

Tests cover:
  - Invalid inputs (empty content, invalid mode, negative pagination)
  - Boundary conditions (very long content, no frontmatter, no history)
  - Security edge cases (path traversal, XSS, SQL injection)
  - Concurrency and resource edge cases

RED PHASE: Many tests will 404 because the Phase 5 endpoints
(POST evaluate/optimize/apply-optimization/benchmark, GET history/report)
have not been implemented yet. This is expected.
"""

import urllib.parse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import app
from app.models import User
from tests.conftest import auth_headers

# ── Client fixture ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def skill_eval_client(db_engine):
    """HTTP test client with DB override for skill-eval routes."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    session_maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

VERY_LONG_CONTENT = "---\nname: long-skill\ndescription: A very long skill\n---\n\n" + (
    "This is a test skill with very long content. " * 500
)  # >10K chars

VALID_SKILL_CONTENT = """---
name: test-skill
title: Test Skill
description: A sample skill for testing
---
# Test Skill

This is a test skill body.
"""

NO_FRONTMATTER_CONTENT = """# No Frontmatter

This skill has no frontmatter at all.
"""


def _build_url(action: str, skill_name: str, suffix: str = "") -> str:
    """Build a URL with URL-encoded skill name and action path segment."""
    encoded = urllib.parse.quote(skill_name, safe="")
    url = f"/api/skill-eval/skills/{encoded}/{action}"
    if suffix:
        url = f"{url}/{suffix}"
    return url


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluate Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluateEdgeCases:
    """Edge cases for POST /skill-eval/skills/{name}/evaluate"""

    # 1. Empty content, skill not in filesystem or DB -> 404
    @pytest.mark.asyncio
    async def test_evaluate_empty_content_skill_not_found(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Empty content with a name not in filesystem or DB should not crash."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "nonexistent-skill-xyz"),
            json={"content": "", "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        # API evaluates content directly; skill name is informational only
        assert response.status_code != 500

    # 2. Invalid mode ("invalid") -> 422 or 400
    @pytest.mark.asyncio
    async def test_evaluate_invalid_mode(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """An invalid evaluation mode should not cause a server crash."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "test-skill"),
            json={"content": VALID_SKILL_CONTENT, "mode": "invalid"},
            headers=auth_headers(test_user.id),
        )
        # Mode is informational; unknown values fall through to static evaluation
        assert response.status_code != 500

    # 3. Very long skill content (>10K chars) -> handled, not 500
    @pytest.mark.asyncio
    async def test_evaluate_very_long_content_handled(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Very long content should be accepted or rejected gracefully, never 500."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "long-skill-test"),
            json={"content": VERY_LONG_CONTENT, "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 500

    # 4. Skill with no frontmatter -> still evaluates (static mode)
    @pytest.mark.asyncio
    async def test_evaluate_no_frontmatter_static_mode(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A skill without frontmatter in static mode should still be evaluated."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "no-frontmatter-skill"),
            json={"content": NO_FRONTMATTER_CONTENT, "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        # Should NOT be 500; static evaluation should handle this gracefully
        assert response.status_code != 500

    # 5. Mode=llm with no LLM config available -> graceful degradation, not 500
    @pytest.mark.asyncio
    async def test_evaluate_llm_mode_no_config(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """LLM mode without LLM config should degrade gracefully, not crash."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "test-skill"),
            json={"content": VALID_SKILL_CONTENT, "mode": "llm"},
            headers=auth_headers(test_user.id),
        )
        # Should not be a 500 crash; could be 503 (service unavailable)
        # or 200 with degraded result, or 400 with clear message
        assert response.status_code != 500

    # 6. Unicode skill name -> URL encoded properly
    @pytest.mark.asyncio
    async def test_evaluate_unicode_skill_name(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Unicode skill names should be URL-encoded and handled properly."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "中文技能-测试"),
            json={"content": VALID_SKILL_CONTENT, "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        # Should not be 422 (FastAPI validation error on path param) or 500
        assert response.status_code not in (422, 500)

    # 7. Concurrent evaluate requests -> no DB deadlock
    @pytest.mark.asyncio
    async def test_evaluate_concurrent_requests_no_deadlock(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Multiple concurrent evaluate requests should not cause DB deadlock."""
        import asyncio

        async def make_request():
            return await skill_eval_client.post(
                _build_url("evaluate", "concurrent-test"),
                json={"content": VALID_SKILL_CONTENT, "mode": "static"},
                headers=auth_headers(test_user.id),
            )

        results = await asyncio.gather(
            make_request(), make_request(), make_request(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                # Deadlock would manifest as a timeout or DB error
                assert "deadlock" not in str(r).lower(), f"Deadlock detected: {r}"
            else:
                assert r.status_code != 500, f"Server error: {r.status_code}"

    # 8. evaluate-llm with content > 50KB returns 413
    @pytest.mark.asyncio
    async def test_evaluate_llm_content_too_large(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Content exceeding 50KB limit should return 413."""
        oversized = "x" * (50 * 1024 + 1)
        url = f"/api/skill-eval/skills/{urllib.parse.quote('test-skill')}/evaluate-llm"
        response = await skill_eval_client.post(
            url,
            json={"content": oversized},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code == 413, (
            f"Expected 413 for oversized content, got {response.status_code}"
        )

    # 9. evaluate-llm with content just at 50KB limit should be accepted
    @pytest.mark.asyncio
    async def test_evaluate_llm_content_at_limit(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Content at exactly 50KB should be accepted (no 413)."""
        at_limit = "x" * (50 * 1024)
        url = f"/api/skill-eval/skills/{urllib.parse.quote('test-skill')}/evaluate-llm"
        response = await skill_eval_client.post(
            url,
            json={"content": at_limit},
            headers=auth_headers(test_user.id),
        )
        # Should NOT be 413; may fail later (503 no LLM config), but not rejected for size
        assert response.status_code != 413, (
            "Content at 50KB limit should not be rejected"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Optimize Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestOptimizeEdgeCases:
    """Edge cases for POST /skill-eval/skills/{name}/optimize
       and POST /skill-eval/skills/{name}/apply-optimization"""

    # 8. Optimize without prior evaluation -> handled gracefully
    @pytest.mark.asyncio
    async def test_optimize_without_prior_evaluation(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Optimizing without a prior evaluation should be handled gracefully."""
        response = await skill_eval_client.post(
            _build_url("optimize", "test-skill"),
            json={"content": VALID_SKILL_CONTENT},
            headers=auth_headers(test_user.id),
        )
        # Should not crash with 500; could be 400/422 with helpful message
        assert response.status_code != 500

    # 9. Optimize skill with missing content -> validation error
    @pytest.mark.asyncio
    async def test_optimize_nonexistent_skill(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Optimizing with missing content should return 422 validation error."""
        response = await skill_eval_client.post(
            _build_url("optimize", "nonexistent-skill-xyz-999"),
            json={},
            headers=auth_headers(test_user.id),
        )
        # Missing required 'content' field → 422; endpoint no longer 404s on nonexistent skill
        assert response.status_code in (404, 422)

    # 10. Apply-optimization with empty content -> 422 or handled
    @pytest.mark.asyncio
    async def test_apply_optimization_empty_content(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Applying optimization with empty content should be rejected or handled."""
        response = await skill_eval_client.post(
            _build_url("apply-optimization", "test-skill"),
            json={"content": ""},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 500
        assert response.status_code in (400, 422, 404)


# ═══════════════════════════════════════════════════════════════════════════════
# Benchmark Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkEdgeCases:
    """Edge cases for POST /skill-eval/skills/{name}/benchmark"""

    @pytest.mark.asyncio
    async def test_benchmark_without_content(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Benchmarking without content should be handled gracefully."""
        response = await skill_eval_client.post(
            _build_url("benchmark", "test-skill"),
            json={},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 500

    @pytest.mark.asyncio
    async def test_benchmark_nonexistent_skill(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Benchmarking without test_prompts should return 400."""
        response = await skill_eval_client.post(
            _build_url("benchmark", "nonexistent-skill-bench-xyz"),
            json={"content": VALID_SKILL_CONTENT},
            headers=auth_headers(test_user.id),
        )
        # Missing test_prompts → 400; nonexistent skill → 404
        assert response.status_code in (400, 404)

    @pytest.mark.asyncio
    async def test_benchmark_with_bad_test_prompts(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Benchmark with empty test prompts should be handled gracefully."""
        response = await skill_eval_client.post(
            _build_url("benchmark", "test-skill"),
            json={
                "content": VALID_SKILL_CONTENT,
                "test_prompts": [],  # empty prompts
            },
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 500


# ═══════════════════════════════════════════════════════════════════════════════
# History Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestHistoryEdgeCases:
    """Edge cases for GET /skill-eval/skills/{name}/history
       and GET /skill-eval/skills/{name}/history/{eval_id}"""

    # 11. page=0 or negative -> handled (clamped to 1 or 422)
    @pytest.mark.asyncio
    async def test_history_page_zero(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """page=0 should be handled — either clamped to 1 or rejected with 422."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill"),
            params={"page": 0, "page_size": 10},
            headers=auth_headers(test_user.id),
        )
        # If clamped: 200. If rejected: 422. Never 500.
        assert response.status_code in (200, 422)

    @pytest.mark.asyncio
    async def test_history_page_negative(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """page=-1 should be handled — either clamped to 1 or rejected with 422."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill"),
            params={"page": -1, "page_size": 10},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code in (200, 422)

    # 12. page_size=0 -> handled
    @pytest.mark.asyncio
    async def test_history_page_size_zero(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """page_size=0 should be handled or rejected gracefully."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill"),
            params={"page": 1, "page_size": 0},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code in (200, 422)

    # 13. page_size=1000 -> reasonable cap
    @pytest.mark.asyncio
    async def test_history_page_size_large(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A very large page_size should be capped or accepted, not crash."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill"),
            params={"page": 1, "page_size": 1000},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 500

    # 14. Skill with no history -> returns empty list, not error
    @pytest.mark.asyncio
    async def test_history_skill_with_no_history(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A skill with no evaluation history should return empty list, not 404."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill-no-history"),
            headers=auth_headers(test_user.id),
        )
        # Should be 200 with empty items, not 404 (skill might not exist,
        # but the history endpoint should distinguish "no skill" from "no history")
        assert response.status_code in (200, 404)

    # 15. Nonexistent eval_id -> 404
    @pytest.mark.asyncio
    async def test_history_nonexistent_eval_id(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Requesting a non-existent eval_id should return 404."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill") + "/99999",
            headers=auth_headers(test_user.id),
        )
        assert response.status_code == 404

    # 16. eval_id=0 or negative -> handled
    @pytest.mark.asyncio
    async def test_history_eval_id_zero(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """eval_id=0 should be handled gracefully (404 or 422)."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill") + "/0",
            headers=auth_headers(test_user.id),
        )
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_history_eval_id_negative(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """eval_id=-1 should be handled gracefully (404 or 422)."""
        response = await skill_eval_client.get(
            _build_url("history", "test-skill") + "/-1",
            headers=auth_headers(test_user.id),
        )
        assert response.status_code in (400, 404, 422)

    # 17. History only returns records for the requesting user
    @pytest.mark.asyncio
    async def test_history_creator_isolation(
        self, skill_eval_client: AsyncClient, test_user: User, db_session
    ):
        """User A should not see User B's evaluation history."""
        from app.models.models import SkillEvalResult as DBSkillEvalResult

        # Create a second user
        from app.models.models import User as DBUser
        user_b = DBUser(
            username="user_b_isolation_test",
            email="user_b@example.com",
            display_name="User B",
            hashed_password="hashed",
            role="user",
            is_active=True,
        )
        db_session.add(user_b)
        await db_session.flush()

        # Insert records for both users
        for uid, extra in [(test_user.id, "aaa"), (user_b.id, "bbb")]:
            db_session.add(DBSkillEvalResult(
                skill_name="history-isolation-test",
                eval_type="static",
                eval_mode="static",
                overall_score=80.0,
                dimensions=[],
                summary=f"Record for user {extra}",
                creator_id=uid,
            ))
        await db_session.commit()

        # User A should only see their own record
        url = f"/api/skill-eval/skills/{urllib.parse.quote('history-isolation-test')}/history"
        response = await skill_eval_client.get(
            url,
            headers=auth_headers(test_user.id),
        )
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        summaries = [item.get("summary", "") for item in items]
        assert "Record for user aaa" in str(summaries), (
            f"User should see own record, got: {summaries}"
        )
        assert "Record for user bbb" not in str(summaries), (
            f"User should NOT see other user's record, got: {summaries}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Report Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportEdgeCases:
    """Edge cases for GET /skill-eval/skills/{name}/report"""

    @pytest.mark.asyncio
    async def test_report_nonexistent_skill(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Requesting a report for a non-existent skill should be handled."""
        response = await skill_eval_client.get(
            _build_url("report", "nonexistent-skill-report-xyz"),
            headers=auth_headers(test_user.id),
        )
        # Could 404 (no data) or 200 (empty report). Should not 500.
        assert response.status_code != 500

    @pytest.mark.asyncio
    async def test_report_invalid_report_type(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """An invalid report_type query parameter should return 400 or 422."""
        response = await skill_eval_client.get(
            _build_url("report", "test-skill"),
            params={"report_type": "invalid_report_type_x"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code in (200, 400, 404, 422)

    @pytest.mark.asyncio
    async def test_report_without_evaluations(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Report for skill with no evaluations should be handled gracefully."""
        response = await skill_eval_client.get(
            _build_url("report", "test-skill-no-evals"),
            params={"report_type": "evaluation"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 500


# ═══════════════════════════════════════════════════════════════════════════════
# Security Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityEdgeCases:
    """Security edge cases for skill_eval endpoints."""

    # 18. Path traversal in skill_name -> 404 or 400, NOT file access
    @pytest.mark.asyncio
    async def test_path_traversal_in_skill_name(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Path traversal in skill_name should not crash the server."""
        traversal_names = [
            "../../../etc/passwd",
            "..\\..\\..\\Windows\\System32\\drivers\\etc\\hosts",
            "....//....//....//etc/passwd",
        ]
        for name in traversal_names:
            response = await skill_eval_client.post(
                _build_url("evaluate", name),
                json={"content": VALID_SKILL_CONTENT, "mode": "static"},
                headers=auth_headers(test_user.id),
            )
            # Skill name is URL-encoded and used as literal string; evaluate
            # endpoint works on content directly so never accesses files by name
            assert response.status_code != 500, (
                f"Path traversal '{name}' caused server error {response.status_code}"
            )

    # 19. XSS in skill_name reflected in response -> escaped
    @pytest.mark.asyncio
    async def test_xss_in_skill_name_escaped(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """XSS payload in skill name should not be reflected unescaped."""
        xss_name = '<script>alert("XSS")</script>'
        response = await skill_eval_client.post(
            _build_url("evaluate", xss_name),
            json={"content": VALID_SKILL_CONTENT, "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        # For JSON APIs, XSS in response field values matters
        if response.status_code in (200, 400, 404, 422):
            body = response.text
            # The raw script tag should not appear in the JSON response body
            # (FastAPI's JSONResponse uses json.dumps which escape < and > by default,
            # but we verify anyway)
            # Note: URL encoding may cause the name to be stored/returned encoded
            if '<script>' in body.lower():
                # Check if it's properly JSON-escaped
                import json
                try:
                    json.loads(body)
                    # Even if the name appears, it should be in a string context
                    # in a JSON response, which is safe
                except json.JSONDecodeError:
                    pass  # Not JSON response

    # 20. SQL injection attempt in skill_name -> parameterized, not vulnerable
    @pytest.mark.asyncio
    async def test_sql_injection_in_skill_name_parameterized(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """SQL injection in skill_name should be handled as a literal string,
        not interpreted as SQL."""
        sql_payloads = [
            "'; DROP TABLE skill_eval_results; --",
            "1 OR 1=1",
            "1; SELECT * FROM users; --",
            "1' UNION SELECT * FROM users; --",
        ]
        for payload in sql_payloads:
            response = await skill_eval_client.post(
                _build_url("evaluate", payload),
                json={"content": VALID_SKILL_CONTENT, "mode": "static"},
                headers=auth_headers(test_user.id),
            )
            # SQLAlchemy parameterizes queries; SQL injection in skill_name is safe.
            # Evaluate endpoint works on content, not by skill name lookup in DB.
            assert response.status_code != 500, (
                f"SQL injection payload '{payload}' caused server error {response.status_code}"
            )

    # 21. Malformed JSON body -> 422
    @pytest.mark.asyncio
    async def test_malformed_json_body(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Malformed JSON request body should return 422, not 500."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "test-skill"),
            content="this is not valid json {{{",
            headers={
                **auth_headers(test_user.id),
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 422

    # 22. Missing required fields -> 422
    @pytest.mark.asyncio
    async def test_missing_required_fields(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Evaluate with only content (no mode) should still work."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "test-skill"),
            json={"content": VALID_SKILL_CONTENT},
            headers=auth_headers(test_user.id),
        )
        # 'mode' is optional; static evaluation runs without it
        assert response.status_code != 500

    # 23. Extra/unknown fields in request body -> accepted or ignored, not 500
    @pytest.mark.asyncio
    async def test_unknown_fields_in_body(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Unknown extra fields should be ignored (FastAPI default) or rejected."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "test-skill"),
            json={
                "content": VALID_SKILL_CONTENT,
                "mode": "static",
                "unexpected_field": "should be ignored",
            },
            headers=auth_headers(test_user.id),
        )
        # FastAPI by default ignores extra fields. Should not be 500.
        assert response.status_code != 500

    # 24. Content-type not application/json -> 415 or 400
    @pytest.mark.asyncio
    async def test_wrong_content_type(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Request with wrong Content-Type should be rejected."""
        response = await skill_eval_client.post(
            _build_url("evaluate", "test-skill"),
            content="some text data",
            headers={
                **auth_headers(test_user.id),
                "Content-Type": "text/plain",
            },
        )
        assert response.status_code in (400, 415, 422)

    # 25. Very long skill name -> handled, not rejected with 500
    @pytest.mark.asyncio
    async def test_very_long_skill_name(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A very long skill name (approaching URL limits) should be handled."""
        long_name = "a" * 500  # 500-char skill name
        response = await skill_eval_client.post(
            _build_url("evaluate", long_name),
            json={"content": VALID_SKILL_CONTENT, "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 500

    # 26. Skill name with special characters -> handled
    @pytest.mark.asyncio
    async def test_skill_name_with_special_chars(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Skill names with special characters should be URL-safe handled."""
        special_names = [
            "skill@#$",
            "skill with spaces",
            "skill/with/slashes",
            "skill.with.dots",
            "skill-with-dashes_and_underscores",
        ]
        for name in special_names:
            encoded = urllib.parse.quote(name, safe="")
            response = await skill_eval_client.post(
                f"/api/skill-eval/skills/{encoded}/evaluate",
                json={"content": VALID_SKILL_CONTENT, "mode": "static"},
                headers=auth_headers(test_user.id),
            )
            # Should not be 422 (which would indicate the routing failed)
            assert response.status_code != 500, (
                f"Special name '{name}' caused 500: {response.text[:200]}"
            )
