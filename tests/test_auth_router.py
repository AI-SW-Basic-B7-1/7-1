"""인증 라우터(app/routers/auth_router.py) 종합 비동기 통합 테스트 모듈.

회원가입, 로그인, get_current_user 의존성 검증 및 예외 상황(중복 아이디,
자격증명 불일치, 만료/위변조 토큰, 미인증 차단)을 체계적으로 검증합니다.
"""

from datetime import timedelta
from typing import AsyncGenerator
import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import create_access_token
from app.database import get_db, init_db
from app.main import app


@pytest.fixture
async def test_client(tmp_path) -> AsyncGenerator[AsyncClient, None]:
    """격리된 테스트용 SQLite DB와 AsyncClient를 제공하는 pytest fixture."""
    test_db_file = tmp_path / "test_auth.db"
    test_db_path = str(test_db_file)

    # 테스트 데이터베이스 스키마 초기화
    await init_db(test_db_path)

    # get_db 의존성 오버라이드
    async def override_get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(test_db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON;")
            yield db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    # 테스트 종료 후 오버라이드 정리
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_register_success(test_client: AsyncClient):
    """정상적인 회원가입 요청 시 201 Created 및 성공 응답을 반환하는지 검증합니다."""
    payload = {
        "username": "newuser123",
        "password": "strongpassword123",
    }
    response = await test_client.post("/api/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["message"] == "회원가입이 완료되었습니다."
    assert data["username"] == "newuser123"


@pytest.mark.anyio
async def test_register_duplicate_username(test_client: AsyncClient):
    """이미 존재하는 아이디로 가입 시도 시 400 Bad Request 에러를 반환하는지 검증합니다."""
    payload = {
        "username": "duplicate_user",
        "password": "password1234",
    }
    # 첫 번째 가입 성공
    res1 = await test_client.post("/api/auth/register", json=payload)
    assert res1.status_code == 201

    # 동일 아이디 재가입 시도 -> 400 오류
    res2 = await test_client.post("/api/auth/register", json=payload)
    assert res2.status_code == 400
    assert res2.json()["detail"] == "이미 존재하는 아이디입니다."


@pytest.mark.anyio
async def test_register_validation_errors(test_client: AsyncClient):
    """길이 제약 및 공백 제약 위반 시 422 Unprocessable Entity 에러를 반환하는지 검증합니다."""
    # 1. 3자 미만 짧은 아이디
    res1 = await test_client.post(
        "/api/auth/register",
        json={"username": "ab", "password": "validpassword"},
    )
    assert res1.status_code == 422
    assert res1.json() == {"detail": "아이디는 최소 3자 이상이어야 합니다."}

    # 2. 4자 미만 짧은 비밀번호
    res2 = await test_client.post(
        "/api/auth/register",
        json={"username": "validuser", "password": "123"},
    )
    assert res2.status_code == 422
    assert res2.json() == {"detail": "비밀번호는 최소 4자 이상이어야 합니다."}

    # 3. 공백 아이디
    res3 = await test_client.post(
        "/api/auth/register",
        json={"username": "   ", "password": "validpassword"},
    )
    assert res3.status_code == 422
    assert res3.json() == {"detail": "아이디는 공백일 수 없습니다."}

    # 4. 필수 비밀번호 누락
    res4 = await test_client.post(
        "/api/auth/register",
        json={"username": "validuser"},
    )
    assert res4.status_code == 422
    assert res4.json() == {"detail": "비밀번호를 입력해 주세요."}


@pytest.mark.anyio
async def test_login_success(test_client: AsyncClient):
    """정상 회원가입 후 올바른 자격증명으로 로그인 시 200 OK와 유효한 JWT 토큰을 반환하는지 검증합니다."""
    # 사전 가입
    await test_client.post(
        "/api/auth/register",
        json={"username": "loginuser", "password": "mypassword123"},
    )

    # 로그인 요청
    response = await test_client.post(
        "/api/auth/login",
        json={"username": "loginuser", "password": "mypassword123"},
    )
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert len(data["access_token"]) > 0
    assert data["token_type"] == "bearer"


@pytest.mark.anyio
async def test_login_wrong_password(test_client: AsyncClient):
    """비밀번호 불일치 시 401 Unauthorized 에러 및 표준 메시지를 반환하는지 검증합니다."""
    await test_client.post(
        "/api/auth/register",
        json={"username": "wrongpwuser", "password": "realpassword"},
    )

    response = await test_client.post(
        "/api/auth/login",
        json={"username": "wrongpwuser", "password": "incorrect_password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "아이디 또는 비밀번호가 올바르지 않습니다."


@pytest.mark.anyio
async def test_login_nonexistent_user(test_client: AsyncClient):
    """존재하지 않는 아이디로 로그인 시 401 Unauthorized 에러를 반환하는지 검증합니다."""
    response = await test_client.post(
        "/api/auth/login",
        json={"username": "nobody_exists", "password": "some_password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "아이디 또는 비밀번호가 올바르지 않습니다."


@pytest.mark.anyio
async def test_get_current_user_valid_token(test_client: AsyncClient):
    """정상적인 Bearer 토큰으로 보호된 엔드포인트(/api/auth/me) 접근 시 200 OK와 사용자 정보를 반환하는지 검증합니다."""
    # 회원가입 및 로그인하여 토큰 획득
    await test_client.post(
        "/api/auth/register",
        json={"username": "authuser", "password": "mypassword123"},
    )
    login_res = await test_client.post(
        "/api/auth/login",
        json={"username": "authuser", "password": "mypassword123"},
    )
    token = login_res.json()["access_token"]

    # 인증 헤더를 첨부하여 프로필 조회
    headers = {"Authorization": f"Bearer {token}"}
    response = await test_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["username"] == "authuser"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.anyio
async def test_get_current_user_missing_token(test_client: AsyncClient):
    """인증 토큰 누락 시 401 Unauthorized 에러 및 표준 메시지를 반환하는지 검증합니다."""
    response = await test_client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "인증 토큰이 유효하지 않거나 만료되었습니다."


@pytest.mark.anyio
async def test_get_current_user_invalid_token(test_client: AsyncClient):
    """위조/변조된 토큰으로 접근 시 401 Unauthorized 에러를 반환하는지 검증합니다."""
    headers = {"Authorization": "Bearer invalid.fake.token"}
    response = await test_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "인증 토큰이 유효하지 않거나 만료되었습니다."


@pytest.mark.anyio
async def test_get_current_user_expired_token(test_client: AsyncClient):
    """만료된 토큰으로 접근 시 401 Unauthorized 에러를 반환하는지 검증합니다."""
    # 사전 사용자 생성
    await test_client.post(
        "/api/auth/register",
        json={"username": "expireduser", "password": "mypassword123"},
    )
    # 만료된 토큰 임의 생성
    expired_token = create_access_token(
        data={"sub": "expireduser"},
        expires_delta=timedelta(seconds=-10),
    )

    headers = {"Authorization": f"Bearer {expired_token}"}
    response = await test_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "인증 토큰이 유효하지 않거나 만료되었습니다."


@pytest.mark.anyio
async def test_health_check(test_client: AsyncClient):
    """서버 헬스체크 엔드포인트(/api/health)가 정상 동작(200 OK)하는지 검증합니다."""
    response = await test_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
