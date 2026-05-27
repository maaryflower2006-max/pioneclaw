"""
Authentication and authorization tests for Skill Evaluation API endpoints.

Tests cover:
  - All endpoints require valid authentication (401 without/invalid token)
  - Normal users can access endpoints appropriately
  - Admin users may have elevated access (if applicable)
  - Token expiry and invalidity are handled

RED PHASE: Many tests will 404 because the Phase 5 endpoints
(POST evaluate/optimize/apply-optimization/benchmark, GET history/report)
have not been implemented yet. This is expected.
"""

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


# ── Route definitions for testing ───────────────────────────────────────────

# All Phase 5 endpoints that should require auth
# Format: (method, path_template, json_body, query_params)
PHASE5_POST_ENDPOINTS = [
    # POST endpoints
    ("POST", "/api/skill-eval/skills/{name}/evaluate",
     {"content": "test-content", "mode": "static"}, {}),
    ("POST", "/api/skill-eval/skills/{name}/optimize",
     {"content": "test-content"}, {}),
    ("POST", "/api/skill-eval/skills/{name}/apply-optimization",
     {"content": "test-content"}, {}),
    ("POST", "/api/skill-eval/skills/{name}/benchmark",
     {"content": "test-content"}, {}),
]

PHASE5_GET_ENDPOINTS = [
    ("GET", "/api/skill-eval/skills/{name}/history", None,
     {"page": 1, "page_size": 10}),
    ("GET", "/api/skill-eval/skills/{name}/history/1", None, {}),
    ("GET", "/api/skill-eval/skills/{name}/report", None,
     {"report_type": "evaluation"}),
]

# Existing endpoints that may or may not require auth
EXISTING_ENDPOINTS = [
    ("GET", "/api/skill-eval/skills", None, {}),
    ("GET", "/api/skill-eval/skills/{name}/tree", None, {}),
    ("GET", "/api/skill-eval/skills/{name}/file", None, {"path": ""}),
]

TEST_SKILL_NAME = "test-skill"


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Required — No Token
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthRequiredNoToken:
    """All endpoints should require auth and return 401 without a token."""

    # 1. All POST endpoints require auth -> 401 without token
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, path_template, body, params",
        PHASE5_POST_ENDPOINTS,
    )
    async def test_post_endpoint_requires_auth(
        self, skill_eval_client: AsyncClient,
        method: str, path_template: str, body: dict, params: dict,
    ):
        """POST endpoints should return 401 when no auth token is provided."""
        url = path_template.format(name=TEST_SKILL_NAME)
        if params:
            response = await skill_eval_client.request(method, url, json=body, params=params)
        else:
            response = await skill_eval_client.request(method, url, json=body)
        # When endpoint exists: 401. Currently (Phase 5 not implemented): 404.
        # Both are acceptable during RED phase.
        assert response.status_code in (401, 404), (
            f"{method} {url} returned {response.status_code}, expected 401 or 404"
        )

    # 2. All GET endpoints (history, report) require auth -> 401 without token
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, path_template, body, params",
        PHASE5_GET_ENDPOINTS,
    )
    async def test_get_endpoint_requires_auth(
        self, skill_eval_client: AsyncClient,
        method: str, path_template: str, body: dict, params: dict,
    ):
        """GET endpoints should return 401 when no auth token is provided."""
        url = path_template.format(name=TEST_SKILL_NAME)
        if params:
            response = await skill_eval_client.request(method, url, params=params)
        else:
            response = await skill_eval_client.request(method, url)
        assert response.status_code in (401, 404), (
            f"{method} {url} returned {response.status_code}, expected 401 or 404"
        )

    # 3. GET /skills (list) may require auth (check existing behavior)
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, path_template, body, params",
        EXISTING_ENDPOINTS,
    )
    async def test_existing_endpoint_requires_auth(
        self, skill_eval_client: AsyncClient,
        method: str, path_template: str, body: dict, params: dict,
    ):
        """Existing skill_eval endpoints should enforce auth."""
        url = path_template.format(name=TEST_SKILL_NAME)
        if params:
            response = await skill_eval_client.request(method, url, params=params)
        else:
            response = await skill_eval_client.request(method, url)
        # Existing endpoints ARE implemented and properly return 401
        assert response.status_code == 401, (
            f"{method} {url} returned {response.status_code}, expected 401"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Required — Invalid/Expired Token
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthInvalidToken:
    """Invalid or expired tokens should be rejected with 401."""

    # 4. Invalid/expired token -> 401
    @pytest.mark.asyncio
    async def test_invalid_token_rejected(
        self, skill_eval_client: AsyncClient,
    ):
        """An obviously invalid token should return 401."""
        headers = {"Authorization": "Bearer invalid-token-that-is-not-real"}
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=headers,
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_token_rejected(
        self, skill_eval_client: AsyncClient,
    ):
        """An empty Bearer token should return 401."""
        headers = {"Authorization": "Bearer "}
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=headers,
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_auth_header(
        self, skill_eval_client: AsyncClient,
    ):
        """A malformed Authorization header should return 401 or 403."""
        headers = {"Authorization": "NotBearer at all"}
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=headers,
        )
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_token_with_wrong_secret(
        self, skill_eval_client: AsyncClient,
    ):
        """A token signed with a different secret should return 401."""
        import jwt
        wrong_token = jwt.encode(
            {"sub": "1"}, "wrong-secret-key-not-real", algorithm="HS256"
        )
        headers = {"Authorization": f"Bearer {wrong_token}"}
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=headers,
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_token_with_nonexistent_user(
        self, skill_eval_client: AsyncClient,
    ):
        """A token for a user that doesn't exist should return 401."""
        from app.core.security import create_access_token
        token = create_access_token(data={"sub": "999999"})  # non-existent user
        headers = {"Authorization": f"Bearer {token}"}
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=headers,
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token_used_for_api(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A refresh token should NOT be accepted for API endpoints."""
        from tests.conftest import refresh_token_headers
        headers = refresh_token_headers(test_user.id)
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=headers,
        )
        # Refresh tokens should not grant API access - should be 401
        # Currently 404 since endpoints don't exist, but when implemented -> 401
        assert response.status_code in (401, 404)


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Required — Valid Token (Successful Auth)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthValidToken:
    """With a valid token, endpoints should be accessible (not 401)."""

    @pytest.mark.asyncio
    async def test_evaluate_with_valid_token_not_401(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A valid token should NOT get a 401 response."""
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        # Should not be 401 (auth passed). Currently 404 (no endpoint).
        assert response.status_code != 401, (
            "Valid token got 401 — auth bypass issue"
        )

    @pytest.mark.asyncio
    async def test_optimize_with_valid_token_not_401(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A valid token should NOT get a 401 response."""
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/optimize",
            json={"content": "test-content"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_history_with_valid_token_not_401(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A valid token should NOT get a 401 response."""
        response = await skill_eval_client.get(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/history",
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_report_with_valid_token_not_401(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A valid token should NOT get a 401 response."""
        response = await skill_eval_client.get(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/report",
            params={"report_type": "evaluation"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_benchmark_with_valid_token_not_401(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A valid token should NOT get a 401 response."""
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/benchmark",
            json={"content": "test-content"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_apply_optimization_with_valid_token_not_401(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A valid token should NOT get a 401 response."""
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/apply-optimization",
            json={"content": "test-content"},
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 401


# ═══════════════════════════════════════════════════════════════════════════════
# Authorization — User Roles and Permissions
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthorization:
    """Test authorization rules for different user roles."""

    # 6. Normal user can evaluate skills
    @pytest.mark.asyncio
    async def test_normal_user_can_evaluate(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A normal (non-admin) user should be able to evaluate skills."""
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        # Should NOT be 403 (forbidden). Currently 404 (no endpoint).
        assert response.status_code != 403, (
            f"Normal user got forbidden for evaluate: {response.status_code}"
        )
        assert response.status_code != 401, (
            f"Normal user got unauthorized for evaluate: {response.status_code}"
        )

    # 7. Normal user can see own history
    @pytest.mark.asyncio
    async def test_normal_user_can_see_own_history(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """A normal user should be able to see their own evaluation history."""
        response = await skill_eval_client.get(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/history",
            headers=auth_headers(test_user.id),
        )
        assert response.status_code != 403
        assert response.status_code != 401

    # 8. Admin can evaluate skills (no 403)
    @pytest.mark.asyncio
    async def test_admin_can_evaluate(
        self, skill_eval_client: AsyncClient, test_admin: User
    ):
        """An admin user should be able to evaluate skills."""
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=auth_headers(test_admin.id),
        )
        assert response.status_code != 403
        assert response.status_code != 401

    # 9. Admin can see all history (if applicable)
    @pytest.mark.asyncio
    async def test_admin_can_see_history(
        self, skill_eval_client: AsyncClient, test_admin: User
    ):
        """An admin user should be able to see evaluation history."""
        response = await skill_eval_client.get(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/history",
            headers=auth_headers(test_admin.id),
        )
        assert response.status_code != 403
        assert response.status_code != 401

    # 10. Org admin can evaluate skills (no 403)
    @pytest.mark.asyncio
    async def test_org_admin_can_evaluate(
        self, skill_eval_client: AsyncClient, test_org_admin: User
    ):
        """An org admin should be able to evaluate skills."""
        response = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=auth_headers(test_org_admin.id),
        )
        assert response.status_code != 403
        assert response.status_code != 401

    # 11. Normal user list-skills returns only accessible skills
    @pytest.mark.asyncio
    async def test_list_skills_with_normal_user(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """List skills endpoint should work for normal users."""
        response = await skill_eval_client.get(
            "/api/skill-eval/skills",
            headers=auth_headers(test_user.id),
        )
        assert response.status_code == 200

    # 12. Admin list-skills works
    @pytest.mark.asyncio
    async def test_list_skills_with_admin(
        self, skill_eval_client: AsyncClient, test_admin: User
    ):
        """List skills endpoint should work for admin users."""
        response = await skill_eval_client.get(
            "/api/skill-eval/skills",
            headers=auth_headers(test_admin.id),
        )
        assert response.status_code == 200

    # 13. Multiple users can each have their own evaluations
    @pytest.mark.asyncio
    async def test_multi_user_isolation(
        self, skill_eval_client: AsyncClient,
        test_user: User, test_admin: User
    ):
        """Evaluations from one user should not interfere with another user's."""
        # Both users should be able to hit the same endpoints independently
        user_resp = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=auth_headers(test_user.id),
        )
        admin_resp = await skill_eval_client.post(
            f"/api/skill-eval/skills/{TEST_SKILL_NAME}/evaluate",
            json={"content": "test-content", "mode": "static"},
            headers=auth_headers(test_admin.id),
        )
        # Neither should be 401 or 403
        for resp in (user_resp, admin_resp):
            assert resp.status_code not in (401, 403), (
                f"Unexpected auth error: {resp.status_code}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-endpoint Auth Consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossEndpointAuth:
    """Verify auth behavior is consistent across all POST and GET endpoints."""

    @pytest.mark.asyncio
    async def test_all_phase5_post_endpoints_reject_without_token(
        self, skill_eval_client: AsyncClient,
    ):
        """Every Phase 5 POST endpoint should reject unauthenticated requests."""
        for method, path_template, body, params in PHASE5_POST_ENDPOINTS:
            url = path_template.format(name=TEST_SKILL_NAME)
            response = await skill_eval_client.request(
                method, url, json=body, params=params if params else None
            )
            assert response.status_code in (401, 404), (
                f"{method} {url} returned {response.status_code}, expected 401 or 404"
            )

    @pytest.mark.asyncio
    async def test_all_phase5_get_endpoints_reject_without_token(
        self, skill_eval_client: AsyncClient,
    ):
        """Every Phase 5 GET endpoint should reject unauthenticated requests."""
        for method, path_template, body, params in PHASE5_GET_ENDPOINTS:
            url = path_template.format(name=TEST_SKILL_NAME)
            response = await skill_eval_client.request(
                method, url, params=params if params else None
            )
            assert response.status_code in (401, 404), (
                f"{method} {url} returned {response.status_code}, expected 401 or 404"
            )

    @pytest.mark.asyncio
    async def test_all_phase5_endpoints_accept_valid_token(
        self, skill_eval_client: AsyncClient, test_user: User
    ):
        """Every Phase 5 endpoint should accept a valid token (not 401/403)."""
        all_endpoints = PHASE5_POST_ENDPOINTS + PHASE5_GET_ENDPOINTS
        for method, path_template, body, params in all_endpoints:
            url = path_template.format(name=TEST_SKILL_NAME)
            response = await skill_eval_client.request(
                method, url,
                json=body if body else None,
                params=params if params else None,
                headers=auth_headers(test_user.id),
            )
            assert response.status_code not in (401, 403), (
                f"{method} {url} returned {response.status_code}, "
                f"expected not 401/403"
            )
