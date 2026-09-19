"""AI 대화 응답 생성 서비스 스텁 모듈.

다른 담당자가 실제 AI API 연동을 구현할 예정이며,
그 전까지 임포트 에러를 방지하기 위한 최소 스텁입니다.
"""

import asyncio
from typing import Dict, List, Optional


class AITimeoutError(asyncio.TimeoutError):
    """AI API가 제한 시간 안에 응답하지 못한 경우의 예외."""


async def generate_chat_response(
    prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """AI 응답 생성 스텁 — 실제 구현 전까지 고정 응답을 반환합니다."""
    return f"[스텁 응답] '{prompt}'에 대한 AI 응답이 아직 구현되지 않았습니다."
