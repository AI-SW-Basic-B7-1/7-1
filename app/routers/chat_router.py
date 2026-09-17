"""채팅 API 라우터 모듈.

본 모듈은 AI 대화 요청(POST /api/chat)과 내 대화 이력 조회(GET /api/me/chats) 엔드포인트를 제공하며,
get_current_user 인증 의존성을 결합하여 실제 로그인한 사용자 식별자(user_id) 기반으로
SQLite 데이터베이스(chat_logs)에 대화를 영속 저장하고 사용자별로 대화 이력을 격리 조회합니다.
"""

import asyncio
import time
from typing import List
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from app.ai_service import generate_chat_response
from app.auth import get_current_user
from app.database import get_db
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
    description="로그인된 사용자가 질문을 전송하면 최근 문맥을 기반으로 AI 답변을 생성하고, 응답 시간과 함께 DB에 저장합니다.",
    responses={
        200: {"description": "답변 생성 성공", "model": ChatResponse},
        400: {"description": "공백 질문 입력 오류", "model": ErrorDetailResponse},
        401: {"description": "미인증 또는 유효하지 않은 토큰", "model": ErrorDetailResponse},
        422: {"description": "질문 길이 500자 초과 등 유효성 검사 실패", "model": ErrorDetailResponse},
        504: {"description": "AI 응답 지연 타임아웃", "model": ErrorDetailResponse},
    },
)
async def send_chat_message(
    request: ChatRequest,
    current_user: UserInDB = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> ChatResponse:
    """사용자의 질문을 수신하여 AI 답변을 생성하고 SQLite chat_logs에 영속 저장합니다.

    get_current_user 의존성을 통해 검증된 사용자의 user_id를 기반으로 저장하며,
    공백 질문 시 400 Bad Request, AI 응답 지연(8.0초 초과) 시 504 Gateway Timeout을 반환합니다.

    Args:
        request (ChatRequest): 사용자가 입력한 질문 데이터
        current_user (UserInDB): get_current_user 의존성을 통해 인증된 현재 사용자 객체
        db (aiosqlite.Connection): 비동기 데이터베이스 커넥션

    Returns:
        ChatResponse: AI 생성 답변과 처리 소요 시간(ms)

    Raises:
        HTTPException: 공백 질문 입력 시 (400), 인증 실패 시 (401), AI 타임아웃/오류 시 (504)
    """
    # 1. 질문 내용 공백 검증 (400 Bad Request)
    cleaned_question = request.question.strip()
    if not cleaned_question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="질문 내용은 공백일 수 없습니다.",
        )

    # 2. 최근 대화 문맥(최근 5쌍) 조회하여 AI 호출 준비
    history = []
    try:
        cursor = await db.execute(
            """
            SELECT question, response
            FROM chat_logs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (current_user.id,),
        )
        rows = await cursor.fetchall()
        for row in reversed(rows):
            history.append({"role": "user", "content": row["question"]})
            history.append({"role": "assistant", "content": row["response"]})
    except Exception:
        # 문맥 조회 실패 시 빈 문맥으로 진행
        history = []

    # 3. AI 응답 생성 및 응답 시간(latency_ms) 정밀 측정
    start_time = time.perf_counter()
    try:
        answer = await generate_chat_response(prompt=cleaned_question, history=history)
    except (asyncio.TimeoutError, TimeoutError):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="현재 AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        )
    latency_ms = int((time.perf_counter() - start_time) * 1000)

    # 4. SQLite chat_logs 테이블에 실제 로그인 사용자 ID(current_user.id)로 영속 저장
    await db.execute(
        """
        INSERT INTO chat_logs (user_id, question, response, latency_ms)
        VALUES (?, ?, ?, ?)
        """,
        (current_user.id, cleaned_question, answer, latency_ms),
    )
    await db.commit()

    return ChatResponse(
        answer=answer,
        latency_ms=latency_ms,
    )


@router.get(
    "/me/chats",
    response_model=List[ChatLogItem],
    status_code=status.HTTP_200_OK,
    summary="내 대화 이력 목록 조회",
    description="현재 로그인한 사용자의 대화 기록 목록을 등록순(과거->최신)으로 조회합니다. 타인의 대화는 격리됩니다.",
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

    Args:
        current_user (UserInDB): get_current_user 의존성을 통해 인증된 현재 사용자 객체
        db (aiosqlite.Connection): 비동기 데이터베이스 커넥션

    Returns:
        List[ChatLogItem]: 로그인 사용자의 대화 기록 목록 (등록순)
    """
    cursor = await db.execute(
        """
        SELECT id, question, response, latency_ms, created_at
        FROM chat_logs
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (current_user.id,),
    )
    rows = await cursor.fetchall()

    chat_history: List[ChatLogItem] = []
    for row in rows:
        chat_history.append(
            ChatLogItem(
                id=row["id"],
                question=row["question"],
                response=row["response"],
                latency_ms=row["latency_ms"],
                created_at=row["created_at"],
            )
        )

    return chat_history
