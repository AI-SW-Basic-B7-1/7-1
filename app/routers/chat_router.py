"""인증된 사용자의 AI 채팅 및 대화 이력 조회 API 모듈."""

from time import perf_counter
from typing import Annotated, Any
from uuid import uuid4

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.ai_service import AITimeoutError, generate_chat_response
from app.auth import decode_access_token
from app.database import (
    get_chat_logs_by_user,
    get_db,
    get_user_by_username,
    save_chat_log,
)
from app.logger import chat_logger
from app.schemas import ChatLogItem, ChatRequest, ChatResponse


router = APIRouter(prefix="/api", tags=["chat"])
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    connection: Annotated[aiosqlite.Connection, Depends(get_db)],
) -> dict[str, Any]:
    """Bearer 토큰을 검증하고 DB에 존재하는 현재 사용자를 반환합니다."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효한 인증 정보가 필요합니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)
    username = payload.get("sub") if payload else None
    if not isinstance(username, str) or not username:
        raise unauthorized

    user = await get_user_by_username(connection, username)
    if user is None:
        raise unauthorized
    return {"id": user["id"], "username": user["username"]}


@router.post("/chat", response_model=ChatResponse)
async def create_chat(
    chat_request: ChatRequest,
    request: Request,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    connection: Annotated[aiosqlite.Connection, Depends(get_db)],
) -> ChatResponse:
    """인증된 사용자의 질문을 AI에 전달하고 결과를 저장합니다."""
    question = chat_request.question
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="질문 내용을 입력해 주세요.",
        )

    user_id = int(current_user["id"])
    request_id = str(uuid4())
    chat_logger.info("request_received user_id=%s path=%s", user_id, request.url.path)
    chat_logger.info(
        "ai_call_start user_id=%s request_id=%s",
        user_id,
        request_id,
    )

    started_at = perf_counter()

    recent_logs = await get_chat_logs_by_user(connection, user_id)
    recent_logs = list(reversed(recent_logs[:5]))

    try:
        answer = await generate_chat_response(question, recent_logs)
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
        "ai_call_success request_id=%s latency_ms=%s",
        request_id,
        latency_ms,
    )

    try:
        chat_id = await save_chat_log(
            connection,
            user_id,
            question,
            answer,
            latency_ms,
        )
    except Exception as exc:
        chat_logger.error("db_save_failed user_id=%s error=%s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="대화 기록을 저장하지 못했습니다.",
        ) from exc

    chat_logger.info("db_save_success user_id=%s chat_id=%s", user_id, chat_id)
    return ChatResponse(answer=answer, latency_ms=latency_ms)


@router.get("/me/chats", response_model=list[ChatLogItem])
async def read_my_chats(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    connection: Annotated[aiosqlite.Connection, Depends(get_db)],
) -> list[ChatLogItem]:
    """현재 로그인한 사용자의 대화 이력을 최신순으로 반환합니다."""
    rows = await get_chat_logs_by_user(connection, int(current_user["id"]))
    chats = [ChatLogItem.model_validate(dict(row)) for row in rows]
    return chats


@router.get("/chat/status")
async def chat_router_status() -> dict[str, str]:
    """채팅 라우터 연결 상태를 반환합니다."""
    return {"status": "chat_router_ready"}
