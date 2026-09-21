"""Gemini AI 서비스의 요청 계약과 응답·타임아웃 처리를 검증하는 단위 테스트 모듈."""

import httpx
import pytest

from app import ai_service
from app.ai_service import AITimeoutError, generate_chat_response


class FakeResponse:
    """Gemini 응답 객체를 대신하는 테스트용 응답 클래스."""

    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        """테스트 응답은 항상 정상 상태로 처리합니다."""

    def json(self) -> dict:
        """미리 지정한 JSON 응답을 반환합니다."""
        return self.payload


class FakeAsyncClient:
    """AsyncClient 호출 인자와 요청 본문을 기록하는 테스트용 클라이언트."""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None, **kwargs):
        self.response = response
        self.error = error
        self.timeout = kwargs.get("timeout")
        self.request = None

    async def __aenter__(self) -> "FakeAsyncClient":
        """비동기 컨텍스트 매니저 진입을 처리합니다."""
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        """비동기 컨텍스트 매니저 종료를 처리합니다."""

    async def post(self, endpoint: str, *, headers: dict, json: dict) -> FakeResponse:
        """Gemini POST 요청의 인자와 본문을 기록하고 응답을 반환합니다."""
        self.request = {"endpoint": endpoint, "headers": headers, "json": json}
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@pytest.mark.anyio
async def test_generate_chat_response_builds_gemini_context(monkeypatch):
    """최근 대화와 현재 질문이 Gemini contents 배열에 올바르게 조립되는지 검증합니다."""
    fake_client = FakeAsyncClient(
        response=FakeResponse(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "  Gemini 답변  "}]}}
                ]
            }
        )
    )
    def make_client(**kwargs):
        """HTTP 클라이언트 생성 시 timeout 값을 기록합니다."""
        fake_client.timeout = kwargs["timeout"]
        return fake_client

    monkeypatch.setattr(ai_service.httpx, "AsyncClient", make_client)

    history = [
        {"question": "이전 질문", "response": "이전 답변"},
    ]
    answer = await generate_chat_response("현재 질문", history)

    assert answer == "Gemini 답변"
    assert fake_client.timeout == ai_service.settings.AI_TIMEOUT_SECONDS
    assert fake_client.request["endpoint"].endswith(
        f"models/{ai_service.settings.GEMINI_MODEL}:generateContent"
    )
    assert fake_client.request["headers"]["x-goog-api-key"] == ai_service.settings.GEMINI_API_KEY
    assert fake_client.request["json"] == {
        "contents": [
            {"role": "user", "parts": [{"text": "이전 질문"}]},
            {"role": "model", "parts": [{"text": "이전 답변"}]},
            {"role": "user", "parts": [{"text": "현재 질문"}]},
        ]
    }


@pytest.mark.anyio
async def test_generate_chat_response_converts_timeout(monkeypatch):
    """Gemini HTTP 타임아웃을 서비스 전용 예외로 변환하는지 검증합니다."""
    fake_client = FakeAsyncClient(error=httpx.TimeoutException("테스트 타임아웃"))
    monkeypatch.setattr(ai_service.httpx, "AsyncClient", lambda **kwargs: fake_client)

    with pytest.raises(AITimeoutError):
        await generate_chat_response("타임아웃 질문", [])


@pytest.mark.anyio
async def test_generate_chat_response_rejects_invalid_payload(monkeypatch):
    """Gemini 응답에 답변 후보가 없으면 명확한 형식 오류를 발생시키는지 검증합니다."""
    fake_client = FakeAsyncClient(response=FakeResponse({"candidates": []}))
    monkeypatch.setattr(ai_service.httpx, "AsyncClient", lambda **kwargs: fake_client)

    with pytest.raises(ValueError, match="Gemini 응답 형식"):
        await generate_chat_response("잘못된 응답 질문", [])
