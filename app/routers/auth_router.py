"""사용자 계정 및 인증 관련 라우터 모듈.

본 모듈은 회원가입, 로그인(JWT 토큰 발급), 미인증 접근 차단용
인증 의존성(get_current_user), 현재 로그인 사용자 정보 조회,
그리고 라우터 연결 상태 확인 엔드포인트를 제공합니다.
"""

from typing import Any, Dict, Optional
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import (
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import UserInDB
from app.schemas import (
    ErrorDetailResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserRegisterResponse,
)

router = APIRouter(prefix="/api/auth", tags=["인증"])


@router.get(
    "/status",
    summary="인증 라우터 연결 상태 확인",
    description="인증 라우터의 정상 연결 및 가용 상태를 확인합니다.",
)
async def auth_router_status() -> dict[str, str]:
    """인증 라우터 연결 상태를 반환합니다."""
    return {"status": "auth_router_ready"}


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="신규 사용자 회원가입",
    description="새로운 사용자 계정을 생성합니다. 비밀번호는 bcrypt로 암호화되며, 아이디 중복 시 400 오류를 반환합니다.",
    responses={
        201: {"description": "회원가입 성공", "model": UserRegisterResponse},
        400: {"description": "아이디 중복", "model": ErrorDetailResponse},
        422: {"description": "유효성 검사 실패"},
    },
)
async def register(
    request: UserRegisterRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> UserRegisterResponse:
    """새로운 사용자 계정을 등록합니다.

    Args:
        request (UserRegisterRequest): 회원가입 요청 데이터 (username, password)
        db (aiosqlite.Connection): 비동기 데이터베이스 커넥션

    Returns:
        UserRegisterResponse: 회원가입 성공 메시지 및 등록된 아이디

    Raises:
        HTTPException: 이미 존재하는 아이디인 경우 (400)
    """
    # 1. 아이디 중복 여부 확인
    cursor = await db.execute(
        "SELECT id FROM users WHERE username = ?",
        (request.username,),
    )
    existing_user = await cursor.fetchone()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 존재하는 아이디입니다.",
        )

    # 2. 비밀번호 bcrypt 단방향 솔팅 해싱
    hashed_password = hash_password(request.password)

    # 3. 데이터베이스에 신규 사용자 저장
    await db.execute(
        "INSERT INTO users (username, hashed_password) VALUES (?, ?)",
        (request.username, hashed_password),
    )
    await db.commit()

    return UserRegisterResponse(
        message="회원가입이 완료되었습니다.",
        username=request.username,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="사용자 로그인 및 JWT 토큰 발급",
    description="아이디와 비밀번호를 검증하고, 유효한 경우 JWT 액세스 토큰을 발급합니다.",
    responses={
        200: {"description": "로그인 성공", "model": TokenResponse},
        401: {"description": "자격 증명 불일치", "model": ErrorDetailResponse},
        422: {"description": "유효성 검사 실패"},
    },
)
async def login(
    request: UserLoginRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> TokenResponse:
    """사용자 아이디와 비밀번호를 검증하고 JWT 액세스 토큰을 발급합니다.

    Args:
        request (UserLoginRequest): 로그인 요청 데이터 (username, password)
        db (aiosqlite.Connection): 비동기 데이터베이스 커넥션

    Returns:
        TokenResponse: 발급된 JWT 액세스 토큰 및 토큰 타입(bearer)

    Raises:
        HTTPException: 아이디가 존재하지 않거나 비밀번호가 불일치하는 경우 (401)
    """
    # 1. 사용자 계정 조회
    cursor = await db.execute(
        "SELECT id, username, hashed_password FROM users WHERE username = ?",
        (request.username,),
    )
    user_row = await cursor.fetchone()

    # 2. 자격 증명 검증 (존재 여부 및 비밀번호 해시 일치 검사)
    if user_row is None or not verify_password(request.password, user_row["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. JWT 액세스 토큰 발급
    token_claims = {
        "sub": user_row["username"],
        "user_id": user_row["id"],
    }
    access_token = create_access_token(data=token_claims)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
    )


@router.get(
    "/me",
    summary="현재 로그인 사용자 정보 조회",
    description="Authorization 헤더의 Bearer 토큰을 검증하여 현재 로그인된 사용자의 기본 정보를 조회합니다.",
    responses={
        200: {"description": "조회 성공"},
        401: {"description": "미인증 또는 유효하지 않은 토큰", "model": ErrorDetailResponse},
    },
)
async def get_my_profile(
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """현재 로그인된 사용자의 계정 정보를 반환합니다.

    Args:
        current_user (UserInDB): get_current_user 의존성을 통해 검증된 현재 사용자

    Returns:
        Dict[str, Any]: 사용자 기본 프로필 정보 (id, username, created_at)
    """
    return {
        "id": current_user.id,
        "username": current_user.username,
        "created_at": current_user.created_at,
    }
