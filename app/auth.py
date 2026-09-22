"""인증 및 보안 유틸리티 모듈.

본 모듈은 비밀번호의 bcrypt 단방향 솔팅 해싱 및 검증,
JWT(JSON Web Token) 액세스 토큰 발급 및 페이로드 검증 유틸리티 함수를 제공합니다.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import aiosqlite
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.config import settings
from app.database import get_db
from app.models import UserInDB


def hash_password(plain_password: str) -> str:
    """평문 비밀번호를 bcrypt 알고리즘으로 단방향 해싱합니다.

    Args:
        plain_password (str): 사용자가 입력한 평문 비밀번호 문자열

    Returns:
        str: 안전하게 솔팅되어 해싱된 비밀번호 문자열
    """
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """입력받은 평문 비밀번호와 기저장된 bcrypt 해시값을 비교 검증합니다.

    Args:
        plain_password (str): 검증할 사용자의 평문 비밀번호
        hashed_password (str): 데이터베이스에 저장된 bcrypt 해시 문자열

    Returns:
        bool: 비밀번호 일치 시 True, 불일치 또는 오류 시 False
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """사용자 클레임 데이터를 기반으로 서명된 JWT 액세스 토큰을 생성합니다.

    Args:
        data (Dict[str, Any]): 토큰 페이로드에 포함할 클레임 딕셔너리 (예: {"sub": "username"})
        expires_delta (Optional[timedelta]): 토큰 만료 시간 (미지정 시 설정 파일 기본값 사용)

    Returns:
        str: 인코딩 및 서명 완료된 JWT 액세스 토큰 문자열
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """JWT 액세스 토큰의 유효성 및 서명을 검증하고 페이로드를 디코딩합니다.

    Args:
        token (str): 검증할 JWT 액세스 토큰 문자열

    Returns:
        Optional[Dict[str, Any]]: 검증 성공 시 페이로드 딕셔너리, 위조/만료 시 None 반환
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except (jwt.PyJWTError, Exception):
        return None


# Swagger UI 및 요청 헤더 파싱을 위한 HTTP Bearer 보안 스키마 (커스텀 401 처리를 위해 auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: aiosqlite.Connection = Depends(get_db),
) -> UserInDB:
    """HTTP Authorization 헤더의 JWT Bearer 토큰을 검증하고 현재 사용자를 반환하는 공통 의존성 함수.

    FastAPI Depends에서 의존성 주입을 명시적으로 분석할 수 있도록 credentials와 db 매개변수를
    직접 선언하였으며, 반환 타입을 UserInDB로 명시하여 타입 안정성을 보장합니다.

    토큰이 누락되었거나, 형식이 올바르지 않거나, 만료/위변조되었거나,
    데이터베이스에 해당 사용자가 존재하지 않는 경우 HTTP 401 Unauthorized 예외를 발생시킵니다.

    Args:
        credentials (Optional[HTTPAuthorizationCredentials]): Authorization 헤더 자격 증명
        db (aiosqlite.Connection): 비동기 데이터베이스 커넥션

    Returns:
        UserInDB: 데이터베이스에서 조회된 현재 인증된 사용자 엔티티

    Raises:
        HTTPException: 인증 토큰이 유효하지 않거나 만료된 경우 (401)
    """
    unauthorized_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 토큰이 유효하지 않거나 만료되었습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or not credentials.credentials:
        raise unauthorized_exception

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise unauthorized_exception

    username: Optional[str] = payload.get("sub")
    if not username:
        raise unauthorized_exception

    # 데이터베이스에서 사용자 존재 여부 조회
    cursor = await db.execute(
        "SELECT user_id, username, hashed_password, created_at FROM users WHERE username = ?",
        (username,),
    )
    user_row = await cursor.fetchone()
    if user_row is None:
        raise unauthorized_exception

    return UserInDB(
        user_id=user_row["user_id"],
        username=user_row["username"],
        hashed_password=user_row["hashed_password"],
        created_at=user_row["created_at"],
    )
