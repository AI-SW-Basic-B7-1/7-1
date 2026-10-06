"""배포 E2E에서 공통으로 쓰는 API·해시 도우미입니다."""

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any


REQUEST_ID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class E2EAccount(dict[str, str]):
    """시험 자격 증명의 기본 표현에서 값을 숨깁니다."""

    def __repr__(self) -> str:
        return "<E2E 테스트 계정>"


def sha256_text(value: str) -> str:
    """문자열 원문을 저장하지 않고 SHA-256 해시를 반환합니다."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def response_request_id(response: Any) -> str:
    """응답 헤더에서 유효한 요청 추적 번호를 확인합니다."""
    request_id = response.headers.get("x-request-id", "")
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise AssertionError("요청 추적 번호 형식이 올바르지 않습니다.")
    return request_id


def api_post(request: Any, base_url: str, path: str, payload: dict, token: str = ""):
    """응답 원문을 출력하지 않는 JSON POST 요청을 보냅니다."""
    if path == "/api/chat":
        wait_for_gemini_slot()
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return request.post(f"{base_url}{path}", data=payload, headers=headers)


def wait_for_gemini_slot() -> None:
    """공유 호출 간격을 지켜 외부 모델의 요청 한도를 넘지 않게 합니다."""
    interval = float(os.environ.get("E2E_MIN_GEMINI_INTERVAL_SECONDS", "0"))
    state_file = os.environ.get("E2E_GEMINI_RATE_LIMIT_FILE", "")
    if interval <= 0 or not state_file:
        return
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        previous = float(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = 0.0
    wait_seconds = interval - (time.time() - previous)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    path.write_text(f"{time.time():.6f}\n", encoding="utf-8")


def verify_visible_records(page: Any, records: list[dict[str, str]]) -> None:
    """브라우저에 복원된 질문·답변을 원문 출력 없이 해시로 확인합니다."""
    expected_questions = [item["question_sha256"] for item in records]
    expected_answers = [item["answer_sha256"] for item in records]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        questions = page.locator(".message-row-user .message-text").all_text_contents()
        answers = page.locator(
            ".message-row-assistant:not(.is-pending):not(.is-error) .message-text"
        ).all_text_contents()
        if (
            [sha256_text(value) for value in questions] == expected_questions
            and [sha256_text(value) for value in answers] == expected_answers
        ):
            return
        page.wait_for_timeout(100)
    raise AssertionError("브라우저에 복원된 질문·답변 해시가 저장 기록과 다릅니다.")


def api_get(request: Any, base_url: str, path: str, token: str = ""):
    """필요한 인증 헤더만 추가해 API GET 요청을 보냅니다."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return request.get(f"{base_url}{path}", headers=headers)


def register_account(request: Any, base_url: str, username: str, password: str):
    """테스트 계정을 등록하고 응답 객체를 반환합니다."""
    return api_post(
        request,
        base_url,
        "/api/auth/register",
        {"username": username, "password": password},
    )


def login_account(request: Any, base_url: str, username: str, password: str) -> str:
    """로그인 토큰을 메모리에서만 반환합니다."""
    response = api_post(
        request,
        base_url,
        "/api/auth/login",
        {"username": username, "password": password},
    )
    if response.status != 200:
        raise AssertionError("테스트 계정 로그인이 실패했습니다.")
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise AssertionError("로그인 응답에 유효한 토큰이 없습니다.")
    return token


def register_and_login(request: Any, base_url: str, account: dict[str, str]) -> str:
    """테스트 계정을 만들거나 기존 실행 계정으로 로그인합니다."""
    response = register_account(
        request, base_url, account["username"], account["password"]
    )
    if response.status not in {201, 400}:
        raise AssertionError("테스트 계정 등록이 실패했습니다.")
    return login_account(request, base_url, account["username"], account["password"])


def chat_history(request: Any, base_url: str, token: str) -> list[dict[str, Any]]:
    """인증된 사용자의 저장된 대화 목록을 반환합니다."""
    response = api_get(request, base_url, "/api/me/chats", token)
    if response.status != 200:
        raise AssertionError("인증된 대화 목록 조회가 실패했습니다.")
    return response.json()
