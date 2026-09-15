"""인증 유틸리티(app/auth.py) 단위 테스트 모듈.

비밀번호 bcrypt 해싱/검증 및 JWT 토큰 발급/검증 기능을 종합적으로 검증합니다.
"""

from datetime import timedelta
import time
import pytest

from app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_and_verify_success():
    """올바른 비밀번호를 해싱하고 검증했을 때 성공(True)하는지 테스트합니다."""
    plain_pw = "password1234!"
    hashed_pw = hash_password(plain_pw)

    # 해시 문자열 검증
    assert hashed_pw != plain_pw
    assert hashed_pw.startswith("$2b$") or hashed_pw.startswith("$2a$")

    # 동일 비밀번호 검증 성공 확인
    assert verify_password(plain_pw, hashed_pw) is True


def test_verify_password_failure():
    """잘못된 비밀번호로 검증 시 실패(False)하는지 테스트합니다."""
    plain_pw = "correct_password"
    wrong_pw = "wrong_password"
    hashed_pw = hash_password(plain_pw)

    assert verify_password(wrong_pw, hashed_pw) is False


def test_hash_password_salting():
    """동일한 비밀번호라도 솔팅(Salting)에 의해 매번 다른 해시값이 생성되는지 테스트합니다."""
    plain_pw = "my_secret_token"
    hash1 = hash_password(plain_pw)
    hash2 = hash_password(plain_pw)

    assert hash1 != hash2
    assert verify_password(plain_pw, hash1) is True
    assert verify_password(plain_pw, hash2) is True


def test_create_and_decode_access_token_success():
    """JWT 토큰 생성 후 정상적으로 디코딩되어 사용자 식별 정보가 복원되는지 테스트합니다."""
    username = "codyssey123"
    token = create_access_token(data={"sub": username})

    assert isinstance(token, str)
    assert len(token) > 0

    payload = decode_access_token(token)
    assert payload is not None
    assert payload.get("sub") == username
    assert "exp" in payload


def test_decode_access_token_expired():
    """만료 시간이 지난 토큰의 경우 decode_access_token이 None을 반환하는지 테스트합니다."""
    username = "expired_user"
    # 만료 시간을 과거(-1초)로 지정하여 즉시 만료된 토큰 생성
    expired_token = create_access_token(
        data={"sub": username},
        expires_delta=timedelta(seconds=-1),
    )

    payload = decode_access_token(expired_token)
    assert payload is None


def test_decode_access_token_invalid():
    """위조되거나 유효하지 않은 임의의 토큰에 대해 None을 반환하는지 테스트합니다."""
    invalid_token = "invalid.jwt.token.string"
    payload = decode_access_token(invalid_token)
    assert payload is None
