"""Gemini API를 이용한 AI 응답 생성 모듈."""

import httpx

from app.config import settings


class AITimeoutError(Exception):
    """AI API가 제한 시간 안에 응답하지 못한 경우의 예외."""


async def generate_chat_response(question: str) -> str:
    """사용자의 질문을 Gemini API에 전달하고 응답을 반환합니다."""
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{settings.GEMINI_MODEL}:generateContent"
    )

    headers = {
        "x-goog-api-key": settings.GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    request_body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": question,
                    }
                ]
            }
        ]
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.AI_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()

    except httpx.TimeoutException as exc:
        raise AITimeoutError("Gemini API 요청이 시간 초과되었습니다.") from exc

    data = response.json()

    try:
        answer = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini 응답 형식이 올바르지 않습니다.") from exc

    if not answer.strip():
        raise ValueError("Gemini 응답이 비어 있습니다.")

    return answer.strip()