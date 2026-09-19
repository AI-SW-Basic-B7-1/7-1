"""채팅 엔드포인트 인증 결합 및 user_id 기반 대화 저장/격리 비동기 통합 테스트 모듈.

본 모듈은 POST /api/chat 및 GET /api/me/chats 엔드포인트의 get_current_user 인증 의존성 결합,
미인증/만료/위조 토큰 차단(401), 공백 질문 방어(400), 500자 초과 방어(422),
AI 응답 영속 저장 및 사용자 간 대화 이력 격리(Multi-tenant Isolation)를 검증합니다.
"""

import asyncio
from typing import AsyncGenerator
from unittest.mock import patch
import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db, init_db
from app.main import app


@pytest.fixture
async def test_client(tmp_path) -> AsyncGenerator[AsyncClient, None]:
    """격리된 테스트용 SQLite DB와 AsyncClient를 제공하는 pytest fixture."""
    test_db_file = tmp_path / "test_chat_auth.db"
    test_db_path = str(test_db_file)

    # 테스트 데이터베이스 스키마 초기화
    await init_db(test_db_path)

    # get_db 의존성 오버라이드
    async def override_get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(test_db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON;")
            yield db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    # 테스트 종료 후 의존성 오버라이드 정리
    app.dependency_overrides.clear()


async def register_and_login(client: AsyncClient, username: str, password: str = "pass1234") -> str:
    """테스트용 계정을 생성하고 로그인하여 액세스 토큰을 반환하는 헬퍼 함수."""
    await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    login_res = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    return login_res.json()["access_token"]


@pytest.mark.anyio
async def test_chat_unauthorized_missing_token(test_client: AsyncClient):
    """Authorization 헤더 없이 POST /api/chat 요청 시 401 Unauthorized를 반환하는지 검증합니다."""
    response = await test_client.post(
        "/api/chat",
        json={"question": "로그인 안 한 사용자의 질문"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "인증 토큰이 유효하지 않거나 만료되었습니다."


@pytest.mark.anyio
async def test_chat_unauthorized_invalid_token(test_client: AsyncClient):
    """위조/변조된 토큰으로 POST /api/chat 요청 시 401 Unauthorized를 반환하는지 검증합니다."""
    headers = {"Authorization": "Bearer forged.token.signature"}
    response = await test_client.post(
        "/api/chat",
        json={"question": "위조 토큰 테스트 질문"},
        headers=headers,
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "인증 토큰이 유효하지 않거나 만료되었습니다."


@pytest.mark.anyio
async def test_get_my_chats_unauthorized(test_client: AsyncClient):
    """Authorization 헤더 없이 GET /api/me/chats 요청 시 401 Unauthorized를 반환하는지 검증합니다."""
    response = await test_client.get("/api/me/chats")
    assert response.status_code == 401
    assert response.json()["detail"] == "인증 토큰이 유효하지 않거나 만료되었습니다."


@pytest.mark.anyio
async def test_chat_empty_question_bad_request(test_client: AsyncClient):
    """공백 질문 전송 시 400 Bad Request와 표준 에러 메시지를 반환하는지 검증합니다."""
    token = await register_and_login(test_client, "user_empty_test")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. 공백 문자열 전송
    res1 = await test_client.post(
        "/api/chat",
        json={"question": "   "},
        headers=headers,
    )
    assert res1.status_code == 400
    assert res1.json()["detail"] == "질문 내용은 공백일 수 없습니다."

    # 2. 빈 문자열 전송
    res2 = await test_client.post(
        "/api/chat",
        json={"question": ""},
        headers=headers,
    )
    assert res2.status_code == 400
    assert res2.json()["detail"] == "질문 내용은 공백일 수 없습니다."


@pytest.mark.anyio
async def test_chat_length_exceeded_validation_error(test_client: AsyncClient):
    """500자를 초과하는 질문 전송 시 422 Unprocessable Entity를 반환하는지 검증합니다."""
    token = await register_and_login(test_client, "user_len_test")
    headers = {"Authorization": f"Bearer {token}"}

    long_question = "가" * 501
    response = await test_client.post(
        "/api/chat",
        json={"question": long_question},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_chat_success_and_db_persistence(test_client: AsyncClient):
    """정상 로그인 사용자가 질문 전송 시 200 OK 응답 및 DB chat_logs에 user_id가 영속 저장되는지 검증합니다."""
    username = "chat_user_success"
    token = await register_and_login(test_client, username)
    headers = {"Authorization": f"Bearer {token}"}

    question = "프로젝트 일정 요약해줘"
    response = await test_client.post(
        "/api/chat",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200

    data = response.json()
    assert "answer" in data
    assert len(data["answer"]) > 0
    assert "latency_ms" in data
    assert isinstance(data["latency_ms"], int)

    # 내 대화 이력 조회(/api/me/chats)를 통해 DB에 저장된 내용 확인
    history_res = await test_client.get("/api/me/chats", headers=headers)
    assert history_res.status_code == 200
    history_list = history_res.json()
    assert len(history_list) == 1
    saved_chat = history_list[0]
    assert saved_chat["question"] == question
    assert saved_chat["response"] == data["answer"]
    assert saved_chat["latency_ms"] == data["latency_ms"]
    assert "id" in saved_chat
    assert "created_at" in saved_chat


@pytest.mark.anyio
async def test_chat_multi_user_isolation(test_client: AsyncClient):
    """사용자 A와 B의 대화 기록이 각각 격리되어 본인의 대화만 조회되는지 검증합니다."""
    token_a = await register_and_login(test_client, "user_alpha")
    token_b = await register_and_login(test_client, "user_beta")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 사용자 A가 대화 전송
    await test_client.post(
        "/api/chat",
        json={"question": "알파의 첫 번째 질문"},
        headers=headers_a,
    )
    await test_client.post(
        "/api/chat",
        json={"question": "알파의 두 번째 질문"},
        headers=headers_a,
    )

    # 사용자 B가 대화 전송
    await test_client.post(
        "/api/chat",
        json={"question": "베타의 유일한 질문"},
        headers=headers_b,
    )

    # 사용자 A의 대화 이력 확인: 알파의 대화 2건만 존재해야 함
    res_a = await test_client.get("/api/me/chats", headers=headers_a)
    assert res_a.status_code == 200
    chats_a = res_a.json()
    assert len(chats_a) == 2
    assert chats_a[0]["question"] == "알파의 첫 번째 질문"
    assert chats_a[1]["question"] == "알파의 두 번째 질문"

    # 사용자 B의 대화 이력 확인: 베타의 대화 1건만 존재해야 함
    res_b = await test_client.get("/api/me/chats", headers=headers_b)
    assert res_b.status_code == 200
    chats_b = res_b.json()
    assert len(chats_b) == 1
    assert chats_b[0]["question"] == "베타의 유일한 질문"


@pytest.mark.anyio
async def test_chat_ai_timeout_504(test_client: AsyncClient):
    """AI 호출 타임아웃 발생 시 504 Gateway Timeout 및 표준 안내 메시지를 반환하는지 검증합니다."""
    token = await register_and_login(test_client, "user_timeout_test")
    headers = {"Authorization": f"Bearer {token}"}

    async def mock_timeout_generate(*args, **kwargs):
        raise asyncio.TimeoutError("AI API 타임아웃")

    with patch("app.routers.chat_router.generate_chat_response", side_effect=mock_timeout_generate):
        response = await test_client.post(
            "/api/chat",
            json={"question": "타임아웃 발생 테스트"},
            headers=headers,
        )
        assert response.status_code == 504
        assert response.json()["detail"] == "현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
