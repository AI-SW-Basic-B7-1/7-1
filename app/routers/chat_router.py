"""인증된 사용자의 AI 채팅 및 대화 이력 조회 API 라우터 모듈."""

from time import perf_counter
from uuid import uuid4

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai_service import AITimeoutError, generate_chat_response
from app.auth import get_current_user
from app.database import (
    conversation_belongs_to_user,
    get_chat_logs_by_user,
    get_db,
    get_recent_chat_logs_by_conversation,
    save_chat_log,
)
from app.logger import chat_logger
from app.models import UserInDB
from app.schemas import ChatLogItem, ChatRequest, ChatResponse, ErrorDetailResponse


router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/chat/status", summary="채팅 라우터 연결 상태 확인")
async def chat_router_status() -> dict[str, str]:
    """채팅 라우터의 정상 연결 및 가용 상태를 반환합니다."""
    return {"status": "chat_router_ready"}


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="AI 챗봇 질문 전송 및 답변 수신",
    description="현재 사용자의 대화방에서 최근 문맥을 읽고 AI 답변을 저장합니다.",
    responses={
        200: {"description": "답변 생성 성공", "model": ChatResponse},
        400: {"description": "공백 질문 입력 오류", "model": ErrorDetailResponse},
        401: {"description": "미인증 또는 유효하지 않은 토큰", "model": ErrorDetailResponse},
        404: {"description": "접근할 수 없는 대화방", "model": ErrorDetailResponse},
        422: {"description": "질문 길이 또는 형식 오류", "model": ErrorDetailResponse},
        500: {"description": "DB 저장 오류", "model": ErrorDetailResponse},
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
    """인증된 사용자의 대화방 문맥으로 답변을 생성하고 기록합니다."""
    question = chat_request.question
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="질문 내용은 공백일 수 없습니다.",
        )

    user_id = current_user.user_id
    conversation_id = chat_request.conversation_id
    request_id = str(uuid4())
    chat_logger.info("request_received user_id=%s path=%s", user_id, request.url.path)

    try:
        history = []
        if conversation_id is not None:
            # 소유권 확인을 AI 호출보다 먼저 수행해 타인 대화방 사용을 차단합니다.
            if not await conversation_belongs_to_user(db, conversation_id, user_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="접근할 수 있는 대화방을 찾지 못했습니다.",
                )
            history = await get_recent_chat_logs_by_conversation(db, conversation_id)
    except HTTPException:
        raise
    except Exception as exc:
        chat_logger.error("db_read_failed user_id=%s error=%s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="대화 기록을 불러오지 못했습니다.",
        ) from exc

    chat_logger.info("ai_call_start user_id=%s request_id=%s", user_id, request_id)
    started_at = perf_counter()
    try:
        answer = await generate_chat_response(question, history)
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

    latency_ms = max(0, round((perf_counter() - started_at) * 1000))
    chat_logger.info(
        "ai_call_success request_id=%s latency_ms=%s", request_id, latency_ms
    )

    try:
        chat_log_id, saved_conversation_id = await save_chat_log(
            db, user_id, question, answer, latency_ms, conversation_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        chat_logger.error("db_save_failed user_id=%s error=%s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="대화 기록을 저장하지 못했습니다.",
        ) from exc

    chat_logger.info("db_save_success user_id=%s chat_id=%s", user_id, chat_log_id)
    return ChatResponse(
        conversation_id=saved_conversation_id,
        answer=answer,
        latency_ms=latency_ms,
    )


@router.get(
    "/me/chats",
    response_model=list[ChatLogItem],
    status_code=status.HTTP_200_OK,
    summary="내 대화 이력 목록 조회",
    description="현재 로그인한 사용자의 대화 기록을 최신순으로 조회합니다.",
    responses={
        200: {"description": "대화 이력 조회 성공", "model": list[ChatLogItem]},
        401: {"description": "미인증 또는 유효하지 않은 토큰", "model": ErrorDetailResponse},
    },
)
async def get_my_chat_history(
    current_user: UserInDB = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[ChatLogItem]:
    """현재 로그인한 사용자의 대화 이력만 반환합니다."""
    rows = await get_chat_logs_by_user(db, current_user.user_id)
    return [ChatLogItem.model_validate(dict(row)) for row in rows]
