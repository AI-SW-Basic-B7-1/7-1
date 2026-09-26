"""채팅 생성과 사용자별 대화 이력 API의 기본 회귀 테스트 모듈."""

from typing import AsyncGenerator
from unittest.mock import Mock

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.ai_service import AIServiceError, AITimeoutError
from app.auth import create_access_token
from app.database import ConversationAccessError, get_db, get_db_connection, init_db
from app.main import app
from app.routers import chat_router


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/api/chat", "/api/me/chats"])
async def test_database_connection_failure_returns_safe_500(chat_client, tmp_path, path):
    """열 수 없는 DB 경로의 연결 실패가 안전한 오류 응답으로 변환됩니다."""
    original_dependency = app.dependency_overrides[get_db]

    async def unavailable_database():
        """파일 대신 디렉터리를 열어 운영체제와 무관하게 연결 실패를 재현합니다."""
        connection = await get_db_connection(tmp_path)
        try:
            yield connection
        finally:
            await connection.close()

    app.dependency_overrides[get_db] = unavailable_database
    try:
        kwargs = {"json": {"question": "질문"}} if path == "/api/chat" else {}
        response = await chat_client.request(
            "POST" if path == "/api/chat" else "GET", path,
            headers=authorization_header("user_one"), **kwargs,
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
        assert response.headers["X-Request-ID"]
    finally:
        app.dependency_overrides[get_db] = original_dependency

    assert (await chat_client.get(
        "/api/me/chats", headers=authorization_header("user_one"),
    )).status_code == 200


@pytest.mark.anyio
async def test_history_query_failure_returns_safe_500(chat_client, monkeypatch):
    """대화 이력 조회 실패를 숨김없이 기록하되 응답에 내부 정보를 노출하지 않습니다."""
    async def fail_query(*args, **kwargs):
        """조회 중 발생한 DB 오류를 재현합니다."""
        raise aiosqlite.OperationalError("노출 금지 테이블 정보")

    with monkeypatch.context() as patch:
        patch.setattr(chat_router, "get_chat_logs_by_user", fail_query)
        response = await chat_client.get(
            "/api/me/chats", headers=authorization_header("user_one"),
        )
    assert response.status_code == 500
    assert response.json() == {"detail": "서버 내부 오류가 발생했습니다."}
    assert response.headers["X-Request-ID"]
    assert (await chat_client.get(
        "/api/me/chats", headers=authorization_header("user_one"),
    )).status_code == 200


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


@pytest.mark.anyio
@pytest.mark.parametrize(
    "target,error_type,expected_status,expected_detail",
    [
        ("generate_chat_response", AIServiceError, 502,
         "AI 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."),
        ("generate_chat_response", RuntimeError, 500, "서버 내부 오류가 발생했습니다."),
        ("generate_chat_response", ValueError, 500, "서버 내부 오류가 발생했습니다."),
        ("save_chat_log", ConversationAccessError, 404,
         "접근할 수 있는 대화방을 찾지 못했습니다."),
        ("save_chat_log", ValueError, 500, "서버 내부 오류가 발생했습니다."),
        ("conversation_belongs_to_user", RuntimeError, 500,
         "서버 내부 오류가 발생했습니다."),
        ("conversation_belongs_to_user", aiosqlite.DatabaseError, 500,
         "대화 기록을 불러오지 못했습니다."),
    ],
)
async def test_error_classification_and_safe_response(
    chat_client, monkeypatch, target, error_type, expected_status, expected_detail,
):
    """오류를 정확히 분류하고 내부 정보 노출 없이 후속 요청을 처리합니다."""
    async def raise_error(*args, **kwargs):
        """응답에 노출되면 안 되는 내부 오류를 재현합니다."""
        raise error_type("노출 금지 내부 정보")

    monkeypatch.setattr(chat_router, target, raise_error)
    payload = {"question": "오류 분류 질문"}
    if target == "conversation_belongs_to_user":
        payload["conversation_id"] = 1

    response = await chat_client.post(
        "/api/chat", headers=authorization_header("user_one"), json=payload,
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert response.headers["X-Request-ID"]
    history = await chat_client.get(
        "/api/me/chats", headers=authorization_header("user_one"),
    )
    assert history.json() == []
    assert (await chat_client.get("/api/health")).status_code == 200
