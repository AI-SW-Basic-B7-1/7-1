"""Gemini 답변을 변경하지 않고 Jev의 구조화된 판정을 조회하는 모듈."""

from dataclasses import dataclass
from math import isfinite
from re import fullmatch

import httpx

from app.config import settings


JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_ACTIONS = frozenset({"accept", "retry", "review"})
ACTION_QUESTION = {
    "type": "choice",
    "instructions": "Decide how this assistant answer should be handled",
    "criteria": {
        "accept": "The answer directly and adequately addresses the user's request",
        "retry": "The answer is clearly inadequate, contradictory, or substantially misses the request",
        "review": "The answer cannot be confidently accepted or rejected",
    },
}


class JevServiceError(Exception):
    """Jev 요청 실패의 로그용 오류 유형만 보관합니다."""

    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


@dataclass(frozen=True)
class JevDecision:
    """Jev 응답에서 관찰 로그에 필요한 필드만 보관합니다."""

    action: str
    confidence: float
    model: str


async def judge_answer(question: str, history: list, answer: str) -> JevDecision:
    """현재 질문과 최근 문맥, Gemini 답변을 Jev Choice 한 개로 평가합니다."""
    if not settings.TYPESAFE_API_KEY:
        raise JevServiceError("missing_api_key")

    state = {
        "question": question,
        "history": [
            {"question": item["question"], "answer": item["response"]}
            for item in history
        ],
        "answer": answer,
    }
    payload = {
        "state": state,
        "model": settings.JEV_MODEL,
        "questions": {"action": ACTION_QUESTION},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.JEV_TIMEOUT_SECONDS) as client:
            response = await client.post(
                JEV_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {settings.TYPESAFE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise JevServiceError("timeout") from exc
    except httpx.HTTPStatusError as exc:
        raise JevServiceError(f"http_{exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise JevServiceError("network") from exc

    try:
        data = response.json()
        decision = data["answers"]["action"]
        action = decision["choice"]
        confidence = decision["confidence"]
        model = data["model"]
        if (
            decision.get("type") != "choice"
            or action not in JEV_ACTIONS
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not isfinite(confidence)
            or not 0 <= confidence <= 1
            or not isinstance(model, str)
            or not fullmatch(r"jev-[A-Za-z0-9.-]+", model)
        ):
            raise ValueError("잘못된 Jev 판정")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise JevServiceError("invalid_response") from exc

    return JevDecision(action=action, confidence=float(confidence), model=model)
