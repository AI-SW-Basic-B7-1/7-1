"""코디세이 AI API 호출 및 Mock 응답 제공 모듈."""

from typing import Any

import httpx

from app.config import settings


class AITimeoutError(Exception):
    """AI API가 제한 시간 안에 응답하지 못한 경우의 예외."""


class AIServiceError(Exception):
    """AI API 호출 또는 응답 처리에 실패한 경우의 예외."""


def _should_use_mock() -> bool:
    """유효한 API 키가 설정되지 않았는지 확인합니다."""
    return (
        not settings.CODESSEY_API_KEY
        or settings.CODESSEY_API_KEY.startswith("your_")
    )


def _extract_answer(payload: dict[str, Any]) -> str:
    """OpenAI 호환 응답에서 답변 문자열을 추출합니다."""
    try:
        answer = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIServiceError("AI 응답 형식이 올바르지 않습니다.") from exc

    if not isinstance(answer, str) or not answer.strip():
        raise AIServiceError("AI 응답 내용이 비어 있습니다.")
    return answer.strip()


async def generate_chat_response(question: str) -> str:
    """질문을 AI API에 전달하고 생성된 답변을 반환합니다."""
    if _should_use_mock():
        return f"Mock AI 응답: {question}"

    endpoint = f"{settings.CODESSEY_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.CODESSEY_API_KEY}",
        "Content-Type": "application/json",
    }
    request_body = {
        "model": settings.AI_MODEL_NAME,
        "messages": [{"role": "user", "content": question}],
    }

    try:
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, headers=headers, json=request_body)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AITimeoutError("AI API 응답 제한 시간을 초과했습니다.") from exc
    except httpx.HTTPError as exc:
        raise AIServiceError("AI API 호출에 실패했습니다.") from exc

    return _extract_answer(response.json())
