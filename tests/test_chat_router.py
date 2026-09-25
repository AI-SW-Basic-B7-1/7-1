"""채팅 생성과 사용자별 대화 이력 API의 기본 회귀 테스트 모듈."""

from typing import AsyncGenerator
from unittest.mock import Mock

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.ai_service import AITimeoutError
from app.auth import create_access_token
from app.database import get_db, get_db_connection, init_db
from app.main import app
from app.routers import chat_router


@pytest.fixture
async def chat_client(tmp_path, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """사용자 두 명이 저장된 임시 DB 기반 API 클라이언트를 제공합니다."""
    database_path = tmp_path / "test_chat.db"
    await init_db(database_path)

    connection = await get_db_connection(database_path)
    try:
        await connection.executemany(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?);",
            [("user_one", "테스트 해시"), ("user_two", "테스트 해시")],
        )
        await connection.commit()
    finally:
        await connection.close()

    async def override_get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
        """요청마다 테스트 DB 연결을 제공합니다."""
        connection = await get_db_connection(database_path)
        try:
            yield connection
        finally:
            await connection.close()

    async def mock_generate_chat_response(question: str, history: list) -> str:
        """외부 API 호출 없이 테스트 답변을 반환합니다."""
        return f"테스트 답변: {question}"

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        chat_router,
        "generate_chat_response",
        mock_generate_chat_response,
    )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


def authorization_header(username: str) -> dict[str, str]:
    """지정한 테스트 사용자의 Bearer 인증 헤더를 생성합니다."""
    token = create_access_token({"sub": username})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_chat_authentication_and_input_validation(chat_client: AsyncClient):
    """미인증, 공백, 길이 초과 질문을 규격에 맞게 차단하는지 검증합니다."""
    unauthorized = await chat_client.post("/api/chat", json={"question": "질문"})
    blank = await chat_client.post(
        "/api/chat",
        headers=authorization_header("user_one"),
        json={"question": "   "},
    )
    too_long = await chat_client.post(
        "/api/chat",
        headers=authorization_header("user_one"),
        json={"question": "가" * 501},
    )

    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert blank.status_code == 400
    assert blank.json() == {"detail": "질문 내용은 공백일 수 없습니다."}
    assert too_long.status_code == 422


@pytest.mark.anyio
async def test_chat_save_logs_and_user_history_isolation(
    chat_client: AsyncClient,
    monkeypatch,
):
    """정상 채팅의 저장과 필수 로그 및 사용자별 이력 격리를 검증합니다."""
    info_log = Mock()
    monkeypatch.setattr(chat_router.chat_logger, "info", info_log)

    response = await chat_client.post(
        "/api/chat",
        headers=authorization_header("user_one"),
        json={"question": "저장할 질문"},
    )
    first_history = await chat_client.get(
        "/api/me/chats",
        headers=authorization_header("user_one"),
    )
    second_history = await chat_client.get(
        "/api/me/chats",
        headers=authorization_header("user_two"),
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "테스트 답변: 저장할 질문"
    assert len(first_history.json()) == 1
    assert first_history.json()[0]["question"] == "저장할 질문"
    assert second_history.json() == []

    formats = [call.args[0] for call in info_log.call_args_list]
    assert "request_received user_id=%s path=%s" in formats
    assert "ai_call_start user_id=%s request_id=%s" in formats
    assert "ai_call_success request_id=%s latency_ms=%s" in formats
    assert "db_save_success user_id=%s chat_id=%s" in formats
    start_call = next(
        call for call in info_log.call_args_list if call.args[0].startswith("ai_call_start ")
    )
    success_call = next(
        call for call in info_log.call_args_list if call.args[0].startswith("ai_call_success ")
    )
    assert start_call.args[2] == success_call.args[1] == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_chat_timeout_returns_504_and_logs_failure(
    chat_client: AsyncClient,
    monkeypatch,
):
    """AI 제한 시간 초과 시 504와 실패 로그를 반환하는지 검증합니다."""
    async def raise_timeout(question: str, history: list) -> str:
        """AI 제한 시간 초과 예외를 발생시킵니다."""
        raise AITimeoutError("테스트 시간 초과")

    error_log = Mock()
    monkeypatch.setattr(chat_router, "generate_chat_response", raise_timeout)
    monkeypatch.setattr(chat_router.chat_logger, "error", error_log)

    response = await chat_client.post(
        "/api/chat",
        headers=authorization_header("user_one"),
        json={"question": "지연 질문"},
    )

    assert response.status_code == 504
    assert response.json() == {
        "detail": "현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
    }
    assert error_log.call_args.args[0] == (
        "ai_call_failed request_id=%s error=%s"
    )
    assert error_log.call_args.args[1] == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_db_failure_returns_500_without_stopping_server(
    chat_client: AsyncClient,
    monkeypatch,
):
    """DB 저장 실패 후에도 서버가 다음 요청을 처리하는지 검증합니다."""
    async def raise_database_error(*args, **kwargs) -> int:
        """테스트용 DB 저장 오류를 발생시킵니다."""
        raise aiosqlite.DatabaseError("테스트 저장 실패")

    error_log = Mock()
    monkeypatch.setattr(chat_router, "save_chat_log", raise_database_error)
    monkeypatch.setattr(chat_router.chat_logger, "error", error_log)

    response = await chat_client.post(
        "/api/chat",
        headers=authorization_header("user_one"),
        json={"question": "저장 실패 질문"},
    )
    health = await chat_client.get("/api/health")

    assert response.status_code == 500
    assert response.json() == {"detail": "대화 기록을 저장하지 못했습니다."}
    assert health.status_code == 200
    assert error_log.call_args.args[0] == "db_save_failed user_id=%s error=%s"
