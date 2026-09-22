"""주제별 대화방을 사용하는 채팅 API 통합 검증 모듈."""

from typing import AsyncGenerator

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import create_access_token
from app.database import get_db, get_db_connection, init_db
from app.main import app
from app.routers import chat_router


@pytest.fixture
async def chat_client(tmp_path, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """주제별 대화 테스트용 사용자와 임시 DB 클라이언트를 제공합니다."""
    database_path = tmp_path / "chat_api.db"
    await init_db(database_path)
    connection = await get_db_connection(database_path)
    try:
        await connection.execute(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?);",
            ("topic_user", "테스트 해시"),
        )
        await connection.commit()
    finally:
        await connection.close()

    async def override_get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
        """요청마다 테스트용 DB 연결을 제공합니다."""
        test_connection = await get_db_connection(database_path)
        try:
            yield test_connection
        finally:
            await test_connection.close()

    async def mock_generate_chat_response(question: str, history: list) -> str:
        """외부 AI를 호출하지 않고 질문에 대응하는 테스트 답변을 반환합니다."""
        return f"테스트 답변: {question}"

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        chat_router,
        "generate_chat_response",
        mock_generate_chat_response,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_chat_api_continues_the_selected_conversation(
    chat_client: AsyncClient,
):
    """응답받은 대화방 번호로 후속 질문을 같은 주제에 저장하는지 검증합니다."""
    token = create_access_token({"sub": "topic_user"})
    headers = {"Authorization": f"Bearer {token}"}

    first_response = await chat_client.post(
        "/api/chat",
        headers=headers,
        json={"question": "AWS 배포 방법"},
    )
    assert first_response.status_code == 200
    conversation_id = first_response.json()["conversation_id"]

    second_response = await chat_client.post(
        "/api/chat",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "question": "Nginx 설정 방법",
        },
    )
    assert second_response.status_code == 200
    assert second_response.json()["conversation_id"] == conversation_id

    history_response = await chat_client.get("/api/me/chats", headers=headers)
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 2
    assert {item["conversation_id"] for item in history} == {conversation_id}
    assert {item["title"] for item in history} == {"AWS 배포 방법"}
    assert all("id" in item for item in history)
