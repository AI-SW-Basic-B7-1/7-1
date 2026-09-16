"""채팅 API 라우터 모듈.

본 모듈은 AI 채팅 요청과 내 대화 이력 조회 엔드포인트를 묶는
FastAPI APIRouter 객체를 제공합니다.
"""

from fastapi import APIRouter


router = APIRouter(
    prefix="/api",
    tags=["chat"],
)


# POST /api/chat, GET /api/me/chats 구현 후 삭제하거나 내부 상태 확인용으로 유지
@router.get("/chat/status")
async def chat_router_status() -> dict[str, str]:
    """채팅 라우터 연결 상태를 반환합니다."""
    return {"status": "chat_router_ready"}
