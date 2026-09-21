"""인증된 사용자의 AI 채팅 및 대화 이력 조회 API 라우터 모듈."""

import time
from typing import List
from uuid import uuid4
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai_service import AITimeoutError, generate_chat_response
from app.auth import get_current_user
from app.database import get_chat_logs_by_user, get_db, save_chat_log
from app.logger import chat_logger
from app.models import UserInDB
from app.schemas import (
    ChatLogItem,
    ChatRequest,
    ChatResponse,
    ErrorDetailResponse,
)

router = APIRouter(
    prefix="/api",
    tags=["chat"],
)


@router.get("/chat/status", summary="채팅 라우터 연결 상태 확인")
async def chat_router_status() -> dict[str, str]:
    """채팅 라우터의 정상 연결 및 가용 상태를 반환합니다."""
    return {"status": "chat_router_ready"}


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="AI 챗봇 질문 전송 및 답변 수신",
    description="로그인된 사용자가 질문을 전송하면 AI 답변을 생성하고, 응답 시간과 함께 DB에 저장합니다.",
    responses={
        200: {"description": "답변 생성 성공", "model": ChatResponse},
        400: {"description": "공백 질문 입력 오류", "model": ErrorDetailResponse},
        401: {"description": "미인증 또는 유효하지 않은 토큰", "model": ErrorDetailResponse},
        422: {"description": "질문 길이 500자 초과 등 유효성 검사 실패", "model": ErrorDetailResponse},
        502: {"description": "AI 서비스 오류", "model": ErrorDetailResponse},
        504: {"description": "AI 응답 지연 타임아웃", "model": ErrorDetailResponse},
    },
)
async def send_chat_message(
    chat_request: ChatRequest,
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> ChatResponse:
    """사용자의 질문을 수신하여 AI 답변을 생성하고 SQLite chat_logs에 영속 저장합니다.

    get_current_user 의존성을 통해 검증된 사용자의 user_id를 기반으로 저장하며,
    공백 질문 시 400 Bad Request, AI 응답 지연(8.0초 초과) 시 504 Gateway Timeout을 반환합니다.
    """
    # 1. 질문 내용 공백 검증 (400 Bad Request)
    cleaned_question = chat_request.question.strip()
    if not cleaned_question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="질문 내용은 공백일 수 없습니다.",
        )

    user_id = current_user.id
    request_id = str(uuid4())
    chat_logger.info("request_received user_id=%s path=%s", user_id, request.url.path)
    chat_logger.info("ai_call_start user_id=%s request_id=%s", user_id, request_id)

    # 2. 최근 대화 문맥을 조립하고 AI 응답 생성 시간을 측정합니다.
    try:
        recent_logs = await get_chat_logs_by_user(db, user_id)
        recent_logs = list(reversed(recent_logs[:5]))
    except Exception as exc:
        chat_logger.error(
            "chat_history_load_failed user_id=%s error=%s",
            user_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="대화 기록을 불러오지 못했습니다.",
        ) from exc

    start_time = time.perf_counter()

    try:
        answer = await generate_chat_response(cleaned_question, recent_logs)     
    except AITimeoutError as exc:
        chat_logger.error("ai_call_failed request_id=%s error=%s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc
    except Exception as exc:
        chat_logger.error("ai_call_failed request_id=%s error=%s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc

    latency_ms = max(0, round((time.perf_counter() - start_time) * 1000))
    chat_logger.info("ai_call_success request_id=%s latency_ms=%s", request_id, latency_ms)

    # 3. SQLite chat_logs 테이블에 실제 로그인 사용자 ID로 영속 저장 및 로깅
    try:
        chat_id = await save_chat_log(db, user_id, cleaned_question, answer, latency_ms)
    except Exception as exc:
        chat_logger.error("db_save_failed user_id=%s error=%s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="대화 기록을 저장하지 못했습니다.",
        ) from exc

    chat_logger.info("db_save_success user_id=%s chat_id=%s", user_id, chat_id)
    return ChatResponse(answer=answer, latency_ms=latency_ms)


@router.get(
    "/me/chats",
    response_model=List[ChatLogItem],
    status_code=status.HTTP_200_OK,
    summary="내 대화 이력 목록 조회",
    description="현재 로그인한 사용자의 대화 기록 목록을 최신순으로 조회합니다. 타인의 대화는 격리됩니다.",
    responses={
        200: {"description": "대화 이력 조회 성공", "model": List[ChatLogItem]},
        401: {"description": "미인증 또는 유효하지 않은 토큰", "model": ErrorDetailResponse},
    },
)
async def get_my_chat_history(
    current_user: UserInDB = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> List[ChatLogItem]:
    """현재 로그인한 사용자의 대화 기록 목록을 반환합니다.

    get_current_user 의존성을 통해 획득한 current_user.id로 필터링하여
    타 사용자의 대화가 일절 노출되지 않는 테넌트 격리를 보장합니다.
    """
    rows = await get_chat_logs_by_user(db, current_user.id)
    return [ChatLogItem.model_validate(dict(row)) for row in rows]
