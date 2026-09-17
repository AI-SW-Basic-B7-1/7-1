"""인증 및 보안 유틸리티 모듈.

본 모듈은 비밀번호의 bcrypt 단방향 솔팅 해싱 및 검증,
JWT(JSON Web Token) 액세스 토큰 발급 및 페이로드 검증 유틸리티 함수를 제공합니다.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import bcrypt
import jwt

from app.config import settings


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


async def get_current_user(*args: Any, **kwargs: Any) -> Any:
    """현재 로그인 사용자 인증 의존성 함수.

    app.routers.auth_router.get_current_user 의존성으로 라우팅하며,
    타 모듈(chat_router 등)에서의 순환 참조 방지 및 편리한 import 경로를 제공합니다.
    """
    from app.routers.auth_router import get_current_user as _get_current_user

    return await _get_current_user(*args, **kwargs)

