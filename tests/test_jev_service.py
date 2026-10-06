"""Jev 요청 계약과 실패 시 정보 노출 방지를 확인합니다."""

import asyncio
from unittest.mock import Mock

import httpx
import pytest

from app import jev_service
from app.config import settings
from app.jev_service import JevServiceError, judge_answer
from app.routers import chat_router
from scripts import benchmark_jev, check_jev


class StubClient:
    """외부 통신 없이 Jev 요청과 응답을 확인하는 클라이언트입니다."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def __aenter__(self):
        """비동기 컨텍스트에 진입합니다."""
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        """비동기 컨텍스트를 종료합니다."""

    async def post(self, endpoint, *, headers, json):
        """전송 값을 기록하고 지정한 결과를 반환합니다."""
        self.calls.append((endpoint, headers, json))
        if self.error:
            raise self.error
        response = Mock()
        response.json.return_value = self.payload
        return response


class DelayedClient(StubClient):
    """단계별 HTTP 제한을 넘지 않는 느린 전체 호출을 재현합니다."""

    async def post(self, endpoint, *, headers, json):
        """전체 시간 제한이 취소할 때까지 응답을 지연합니다."""
        await asyncio.sleep(1)
        return await super().post(endpoint, headers=headers, json=json)


@pytest.mark.anyio
async def test_judge_answer_sends_one_choice_and_recent_context(monkeypatch):
    """질문·최근 문맥·Gemini 답변만 인증된 Jev 엔드포인트로 보냅니다."""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "test-jev-secret")
    monkeypatch.setattr(settings, "JEV_MODEL", "jev-1.13.0")
    client = StubClient({
        "model": "jev-1.13.0",
        "answers": {"action": {
            "type": "choice", "choice": "accept", "confidence": 0.87,
            "probabilities": {"accept": 0.87, "retry": 0.08, "review": 0.05},
        }},
    })
    monkeypatch.setattr(jev_service.httpx, "AsyncClient", lambda **kwargs: client)

    decision = await judge_answer(
        "현재 질문", [{"question": "이전 질문", "response": "이전 답변"}], "Gemini 답변"
    )

    assert (decision.action, decision.confidence, decision.model) == (
        "accept", 0.87, "jev-1.13.0"
    )
    endpoint, headers, body = client.calls[0]
    assert endpoint == "https://api.typesafe.ai/v1/systemone"
    assert headers["Authorization"] == "Bearer test-jev-secret"
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == {
        "question": "현재 질문",
        "history": [{"question": "이전 질문", "answer": "이전 답변"}],
        "answer": "Gemini 답변",
    }
    assert list(body["questions"]) == ["action"]
    assert body["questions"]["action"]["type"] == "choice"


@pytest.mark.anyio
async def test_judge_answer_requires_key_without_sending(monkeypatch):
    """키가 없으면 외부 요청을 만들지 않습니다."""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "")
    with pytest.raises(JevServiceError, match="missing_api_key"):
        await judge_answer("질문", [], "답변")


@pytest.mark.anyio
async def test_judge_answer_classifies_timeout(monkeypatch):
    """짧은 Jev 타임아웃을 서비스 전용 실패로 구분합니다."""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "test-jev-secret")
    client = StubClient(error=httpx.TimeoutException("비밀 내용"))
    monkeypatch.setattr(jev_service.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(JevServiceError) as result:
        await judge_answer("질문", [], "답변")
    assert result.value.error_type == "timeout"


@pytest.mark.anyio
async def test_judge_answer_classifies_malformed_json(monkeypatch):
    """응답 본문을 해석하지 못해도 원문을 노출하지 않습니다."""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "test-jev-secret")

    class MalformedClient(StubClient):
        """잘못된 JSON 응답을 돌려주는 테스트 클라이언트입니다."""

        async def post(self, endpoint, *, headers, json):
            """응답 본문 해석 오류를 재현합니다."""
            response = Mock()
            response.json.side_effect = ValueError("노출 금지 본문")
            return response

    monkeypatch.setattr(jev_service.httpx, "AsyncClient", lambda **kwargs: MalformedClient())
    with pytest.raises(JevServiceError) as result:
        await judge_answer("질문", [], "답변")
    assert result.value.error_type == "invalid_response"


@pytest.mark.anyio
@pytest.mark.parametrize("entrypoint", ["service", "chat", "check", "benchmark"])
async def test_total_timeout_applies_to_every_jev_entrypoint(
    monkeypatch, capsys, entrypoint,
):
    """느린 Jev 호출을 공통 계층에서 제한하고 각 경로가 실패로 기록합니다."""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "test-jev-secret")
    monkeypatch.setattr(settings, "JEV_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(jev_service.httpx, "AsyncClient", lambda **kwargs: DelayedClient())

    if entrypoint == "service":
        with pytest.raises(JevServiceError) as result:
            await judge_answer("질문", [], "답변")
        assert result.value.error_type == "timeout"
    elif entrypoint == "chat":
        warning = Mock()
        monkeypatch.setattr(chat_router.chat_logger, "warning", warning)
        await chat_router.log_jev_decision("질문", [], "답변", "test-request")
        assert warning.call_args.args[0].startswith("jev_failed ")
        assert warning.call_args.args[2] == "timeout"
    elif entrypoint == "check":
        assert await check_jev.main() == 1
        assert "FAILED (timeout)" in capsys.readouterr().out
    else:
        await benchmark_jev.run_benchmark([
            {"question": "질문", "answer": "답변", "expected_action": "retry"}
        ], 1)
        output = capsys.readouterr().out
        assert "effective" in output
        assert "model    " not in output
        assert output.split("effective", 1)[1].splitlines()[0].strip().endswith("1")


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [
    {},
    {"model": "jev-1.13.0", "answers": {"action": {"type": "choice", "choice": "unknown", "confidence": 0.9}}},
    {"model": "jev-1.13.0", "answers": {"action": {"type": "choice", "choice": "accept", "confidence": 2}}},
])
async def test_judge_answer_rejects_invalid_decision(monkeypatch, payload):
    """예상하지 못한 판정·확신도는 사용하지 않습니다."""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "test-jev-secret")
    monkeypatch.setattr(jev_service.httpx, "AsyncClient", lambda **kwargs: StubClient(payload))
    with pytest.raises(JevServiceError) as result:
        await judge_answer("질문", [], "답변")
    assert result.value.error_type == "invalid_response"
