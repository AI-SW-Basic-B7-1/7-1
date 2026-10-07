"""HTTP 요청 추적과 오류 응답의 로그 회귀 검증."""

import asyncio
import io
import logging
from uuid import UUID

import pytest
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient

from app.logger import RequestContextFilter, app_logger, chat_logger, request_id_context
from app.main import create_app


@pytest.fixture
def log_output():
    """실제 포맷 필터를 사용해 요청 로그를 수집합니다."""
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(logging.Formatter("%(message)s%(request_suffix)s"))
    app_logger.addHandler(handler)
    try:
        yield output
    finally:
        app_logger.removeHandler(handler)
        handler.close()


@pytest.mark.anyio
async def test_http_request_logs_and_headers(log_output):
    """정상·인증·검증·경로 오류와 OPTIONS 요청을 비밀값 없이 기록합니다."""
    app = create_app()

    @app.post("/test-input")
    async def test_input(payload: dict):
        return {"ok": True}

    @app.get("/test-unauthorized")
    async def unauthorized():
        raise HTTPException(401, "인증 필요", headers={"WWW-Authenticate": "Bearer"})

    requests = [
        ("GET", "/api/health?secret=query-secret", {}, 200),
        ("POST", "/test-input", {"json": {"password": "body-secret"}}, 200),
        ("POST", "/test-input", {"json": []}, 422),
        ("GET", "/test-unauthorized", {}, 401),
        ("GET", "/missing", {}, 404),
        ("GET", "/static/css/style.css", {}, 200),
        ("OPTIONS", "/api/chat", {"headers": {
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        }}, 200),
    ]
    ids = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method, path, kwargs, expected in requests:
            response = await client.request(method, path, **kwargs)
            assert response.status_code == expected
            ids.append(response.headers["X-Request-ID"])
            assert UUID(ids[-1]).version == 4
            if expected == 401:
                assert response.headers["WWW-Authenticate"] == "Bearer"
    assert len(set(ids)) == len(ids)
    lines = log_output.getvalue().splitlines()
    for request_id in ids:
        matching = [line for line in lines if f"request_id={request_id}" in line]
        assert len(matching) == 2
        assert matching[0].startswith("http_request_started")
        assert matching[1].startswith("http_request_completed")
        assert "duration_ms=" in matching[1]
    assert "query-secret" not in log_output.getvalue()
    assert "body-secret" not in log_output.getvalue()
    assert request_id_context.get() is None


@pytest.mark.anyio
async def test_unhandled_error_is_logged_once(log_output):
    """미처리 예외는 한 번 기록하고 공통 오류 응답에도 ID를 전달합니다."""
    app = create_app()

    @app.get("/test-error")
    async def fail():
        raise RuntimeError("추적용 테스트 오류")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/test-error", headers={"Authorization": "Bearer header-secret"})
    assert response.status_code == 500
    request_id = response.headers["X-Request-ID"]
    logs = log_output.getvalue()
    assert logs.count("http_request_failed") == 1
    assert "http_request_completed" not in logs
    assert "unhandled_exception" not in logs
    assert f"request_id={request_id}" in logs
    assert "Traceback" in logs
    assert "header-secret" not in logs
    assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
    assert request_id_context.get() is None


@pytest.mark.anyio
async def test_concurrent_requests_share_only_their_own_id(log_output):
    """동시 요청의 DB 이벤트와 HTTP 로그가 각 요청 ID에만 연결됩니다."""
    app = create_app()

    @app.get("/test-context/{number}")
    async def context(number: int, request: Request):
        await asyncio.sleep(0)
        chat_logger.info("db_save_success user_id=%s chat_id=%s", number, number)
        return {"request_id": request.state.request_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(*(client.get(f"/test-context/{i}") for i in range(3)))
    for i, response in enumerate(responses):
        request_id = response.headers["X-Request-ID"]
        assert response.json()["request_id"] == request_id
        assert f"db_save_success user_id={i} chat_id={i} request_id={request_id}" in log_output.getvalue()
    assert len({response.headers["X-Request-ID"] for response in responses}) == 3
