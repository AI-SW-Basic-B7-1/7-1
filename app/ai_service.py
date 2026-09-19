"""AI 대화 응답 생성 서비스 모듈.

본 모듈은 코디세이 AI API(OpenAI 호환) 비동기 호출, 슬라이딩 윈도우 문맥 유지,
8.0초 타임아웃 방어 및 외부 API 키 부재 시 동작하는 내장 Mock AI 엔진을 제공합니다.
웹 프레임워크나 DB 의존성이 배제된 순수 비동기 함수 형태로 구현되었습니다.
"""

import asyncio
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings


class AITimeoutError(asyncio.TimeoutError):
    """AI API가 제한 시간 안에 응답하지 못한 경우의 예외."""


class AIServiceError(Exception):
    """AI API 호출 또는 응답 처리에 실패한 경우의 예외."""


def _is_valid_api_key(api_key: str) -> bool:
    """유효한 실제 API 키가 설정되어 있는지 확인합니다."""
    if not api_key or api_key.startswith("your_"):
        return False
    return api_key not in ("your_codessey_api_key", "your_codessey_api_key_here")


def _get_mock_response(prompt: str) -> str:
    """외부 API 키 미설정 또는 테스트 환경에서 반환할 Mock AI 답변을 생성합니다."""
    trimmed = prompt.strip()
    if "일정" in trimmed or "프로젝트" in trimmed:
        return "이번 주 4일 프로토타입 프로젝트 일정은 Day 1 독립 모듈 세팅, Day 2 코어 로직 완성, Day 3 E2E 결합, Day 4 안정성 점검 및 배포 순서로 진행됩니다."
    if "안녕" in trimmed:
        return "안녕하세요! AI 어시스턴트입니다. 무엇을 도와드릴까요?"
    if "역할" in trimmed:
        return "저는 사용자의 질문에 친절하고 정확하게 답변해 드리는 챗봇입니다."

    return f"AI 어시스턴트입니다. 문의하신 '{trimmed}'에 대해 성심껏 안내해 드리겠습니다."


async def generate_chat_response(
    prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """사용자의 질문과 이전 대화 이력을 바탕으로 AI 응답을 비동기로 생성합니다.

    API 키가 미설정된 경우 내장 Mock AI 엔진을 통해 즉각 응답을 반환하며,
    실제 API 키가 존재하는 경우 OpenAI 호환 엔드포인트를 비동기 호출합니다.
    8.0초 타임아웃 발생 시 AITimeoutError를 발생시켜 상위 라우터에서 504로 대응하도록 합니다.

    Args:
        prompt (str): 현재 사용자가 입력한 질문 텍스트
        history (Optional[List[Dict[str, str]]]): 이전 대화 이력 리스트 (최근 3~5쌍)

    Returns:
        str: 생성된 AI 어시스턴트 답변 내용

    Raises:
        AITimeoutError: AI 응답 생성 시간이 설정된 타임아웃(8.0초)을 초과한 경우
        AIServiceError: 외부 API 통신 실패 또는 비정상 응답 발생 시
    """
    # 1. 외부 API 키가 미설정된 경우 내장 Mock AI 엔진으로 즉시 응답
    if not _is_valid_api_key(settings.CODESSEY_API_KEY):
        return _get_mock_response(prompt)

    # 2. 메시지 배열 구성 (슬라이딩 윈도우 문맥 결합)
    messages: List[Dict[str, str]] = [
        {
            "role": "system",
            "content": "당신은 친절하고 정확한 한국어 AI 어시스턴트입니다. 사용자의 질문에 성실하게 답변하세요.",
        }
    ]

    # 이전 대화 이력이 있는 경우 최근 5쌍(10개 메시지)까지 추가
    if history:
        for item in history[-10:]:
            messages.append(item)

    messages.append({"role": "user", "content": prompt})

    # 3. 비동기 HTTP 클라이언트를 통한 AI API 호출 (8.0초 타임아웃 강제)
    endpoint = f"{settings.CODESSEY_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.CODESSEY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.AI_MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            answer: str = data["choices"][0]["message"]["content"].strip()
            return answer
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        raise AITimeoutError("AI API 응답 시간이 8.0초를 초과하였습니다.") from exc
    except Exception as exc:
        raise AIServiceError(f"AI API 호출 중 오류가 발생했습니다: {exc}") from exc
