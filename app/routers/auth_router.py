"""인증 API 라우터 모듈.

본 모듈은 회원가입, 로그인 등 인증 관련 엔드포인트를 묶는
FastAPI APIRouter 객체를 제공합니다.
"""

from fastapi import APIRouter


router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
)


# 회원가입/로그인 엔드포인트 구현 후 삭제하거나 내부 상태 확인용으로 유지
@router.get("/status")
async def auth_router_status() -> dict[str, str]:
    """인증 라우터 연결 상태를 반환합니다."""
    return {"status": "auth_router_ready"}
