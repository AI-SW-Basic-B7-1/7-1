"""인증·입력·계정 격리 API와 사용자 화면을 E2E로 확인합니다."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import time

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    api_get,
    api_post,
    E2EAccount,
    chat_history,
    login_account,
    register_account,
    register_and_login,
    response_request_id,
    sha256_text,
    wait_for_gemini_slot,
)


def _account(base: dict[str, str], suffix: str) -> E2EAccount:
    """시나리오 이름으로 충돌을 피하는 계정 식별자를 만듭니다."""
    return E2EAccount({
        "username": f"{base['username'][:32]}_{suffix}",
        "password": base["password"],
    })


def _http_register(target: str, account: dict[str, str]) -> tuple[int, int]:
    """병렬 가입 요청의 상태와 경과시간만 반환합니다."""
    started = time.perf_counter()
    response = httpx.post(
        f"{target}/api/auth/register",
        json=account,
        timeout=30,
    )
    return response.status_code, round((time.perf_counter() - started) * 1000)


@pytest.mark.e2e_scenario("A01")
def test_a01_missing_and_forged_tokens_are_rejected(page: Page, e2e_target: str, e2e_record):
    """토큰 누락·위조가 채팅과 이력 조회에서 모두 401인지 확인합니다."""
    request = page.context.request
    page.goto(e2e_target)
    expect(page.locator("#question-input")).to_be_disabled()
    chat_missing = api_post(request, e2e_target, "/api/chat", {"question": "E2E"})
    history_missing = api_get(request, e2e_target, "/api/me/chats")
    chat_forged = api_post(
        request,
        e2e_target,
        "/api/chat",
        {"question": "E2E"},
        "not.a.valid.token",
    )
    assert chat_missing.status == history_missing.status == chat_forged.status == 401
    e2e_record("A01", request_id=response_request_id(chat_missing), status=401)


@pytest.mark.e2e_scenario("A03")
def test_a03_password_ascii_and_utf8_byte_boundaries(
    page: Page,
    e2e_target: str,
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """ASCII와 한글 비밀번호의 bcrypt 72바이트 경계를 실제 가입·로그인으로 확인합니다."""
    request = page.context.request
    ascii_account = _account(e2e_secondary_account, "a03ascii")
    ascii_valid = register_account(request, e2e_target, ascii_account["username"], "a" * 72)
    assert ascii_valid.status == 201
    ascii_token = login_account(request, e2e_target, ascii_account["username"], "a" * 72)
    ascii_invalid = register_account(
        request,
        e2e_target,
        ascii_account["username"] + "x",
        "a" * 73,
    )

    korean_account = _account(e2e_secondary_account, "a03korean")
    korean_valid_password = "한" * 24
    korean_invalid_password = "한" * 25
    korean_valid = register_account(
        request,
        e2e_target,
        korean_account["username"],
        korean_valid_password,
    )
    korean_token = login_account(
        request,
        e2e_target,
        korean_account["username"],
        korean_valid_password,
    )
    korean_invalid = register_account(
        request,
        e2e_target,
        korean_account["username"] + "x",
        korean_invalid_password,
    )

    assert ascii_invalid.status == korean_invalid.status == 422
    assert ascii_token and korean_token
    e2e_record("A03", status=422)


@pytest.mark.e2e_scenario("A04")
def test_a04_duplicate_concurrent_signup_and_failed_login(
    page: Page,
    e2e_target: str,
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """동시 중복 가입 한 건만 성공하고 로그인 실패는 401인지 확인합니다."""
    account = _account(e2e_secondary_account, "a04")
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: _http_register(e2e_target, account), range(2)))
    assert sorted(status for status, _ in outcomes) == [201, 400]
    duplicate = register_account(
        page.context.request,
        e2e_target,
        account["username"],
        account["password"],
    )
    failed_login = api_post(
        page.context.request,
        e2e_target,
        "/api/auth/login",
        {"username": account["username"], "password": "wrong-password"},
    )
    assert duplicate.status == 400 and failed_login.status == 401
    e2e_record("A04", status=failed_login.status)


@pytest.mark.e2e_scenario("A05")
def test_a05_health_responds_while_signup_hashes_password(
    page: Page,
    e2e_target: str,
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """bcrypt 가입 요청과 동시에 서버 상태 요청이 성공하는지 확인합니다."""
    account = _account(e2e_secondary_account, "a05")
    with ThreadPoolExecutor(max_workers=1) as executor:
        signup_future = executor.submit(_http_register, e2e_target, account)
        health_started = time.perf_counter()
        health = page.context.request.get(f"{e2e_target}/api/health", timeout=15000)
        health_elapsed = round((time.perf_counter() - health_started) * 1000)
        signup_status, signup_elapsed = signup_future.result(timeout=30)
    assert health.status == 200 and signup_status == 201
    e2e_record("A05", status=health.status, elapsed_ms=max(health_elapsed, signup_elapsed))


@pytest.mark.e2e_scenario("V01")
def test_v01_blank_and_501_character_questions_do_not_write(
    page: Page,
    e2e_target: str,
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """공백과 501자 질문의 서버 응답 및 저장 이력 불변을 확인합니다."""
    account = _account(e2e_secondary_account, "v01")
    token = register_and_login(page.context.request, e2e_target, account)
    before_count = len(chat_history(page.context.request, e2e_target, token))
    blank = api_post(
        page.context.request,
        e2e_target,
        "/api/chat",
        {"question": " \t "},
        token,
    )
    over_limit = api_post(
        page.context.request,
        e2e_target,
        "/api/chat",
        {"question": "x" * 501},
        token,
    )
    after_count = len(chat_history(page.context.request, e2e_target, token))
    assert blank.status == 400 and over_limit.status == 422
    assert after_count == before_count
    e2e_record("V01", request_id=response_request_id(blank), status=blank.status, history_count=after_count)
    e2e_record("V01", request_id=response_request_id(over_limit), status=over_limit.status, history_count=after_count)


@pytest.mark.e2e_scenario("V02")
def test_v02_ui_blocks_blank_and_overlong_questions_before_network(
    page: Page,
    e2e_target: str,
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """화면에서 공백·501자 입력을 안내하고 API 요청을 보내지 않는지 확인합니다."""
    account = _account(e2e_secondary_account, "v02")
    register_account(
        page.context.request,
        e2e_target,
        account["username"],
        account["password"],
    )
    page.goto(e2e_target)
    page.get_by_role("button", name="로그인").click()
    page.locator("#login-username").fill(account["username"])
    page.locator("#login-password").fill(account["password"])
    page.locator("#login-submit-button").click()
    expect(page.get_by_role("button", name="로그아웃")).to_be_visible()
    chat_requests: list[str] = []
    page.on(
        "request",
        lambda request: chat_requests.append(request.url)
        if request.method == "POST" and request.url.endswith("/api/chat")
        else None,
    )
    question = page.locator("#question-input")
    question.fill(" \t ")
    page.locator("#send-button").click()
    expect(page.locator("#toast-region")).to_contain_text("질문을 입력해 주세요.")
    question.fill("x" * 501)
    page.locator("#send-button").click()
    expect(page.locator("#toast-region")).to_contain_text("500자 이하")
    assert not chat_requests
    e2e_record("V02", ui_blocked="blank,501")


@pytest.mark.e2e_scenario("I01")
def test_i01_user_histories_are_separate(
    page: Page,
    e2e_target: str,
    e2e_account: dict[str, str],
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """서로 다른 사용자의 채팅과 이력 API 결과가 분리되는지 확인합니다."""
    request = page.context.request
    account_a = _account(e2e_account, "i01a")
    account_b = _account(e2e_secondary_account, "i01b")
    token_a = register_and_login(request, e2e_target, account_a)
    token_b = register_and_login(request, e2e_target, account_b)
    question_a = "E2E 사용자 A 격리 " + os.environ.get("E2E_RUN_ID", "local")
    question_b = "E2E 사용자 B 격리 " + os.environ.get("E2E_RUN_ID", "local")
    response_a = api_post(
        request, e2e_target, "/api/chat", {"question": question_a}, token_a
    )
    response_b = api_post(
        request, e2e_target, "/api/chat", {"question": question_b}, token_b
    )
    assert response_a.status == response_b.status == 200
    conversation_a = response_a.json()["conversation_id"]
    conversation_b = response_b.json()["conversation_id"]
    history_a = chat_history(request, e2e_target, token_a)
    history_b = chat_history(request, e2e_target, token_b)
    assert conversation_a != conversation_b
    assert {row["conversation_id"] for row in history_a} == {conversation_a}
    assert {row["conversation_id"] for row in history_b} == {conversation_b}
    assert all(sha256_text(row["question"]) != sha256_text(question_b) for row in history_a)
    assert all(sha256_text(row["question"]) != sha256_text(question_a) for row in history_b)
    e2e_record("I01", request_id=response_request_id(response_a), status=200, conversation_id=conversation_a)


@pytest.mark.e2e_scenario("I02")
def test_i02_cross_user_conversation_is_not_visible_or_writable(
    page: Page,
    e2e_target: str,
    e2e_account: dict[str, str],
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """다른 사용자의 대화방을 지정한 요청이 404이고 양쪽 이력이 변하지 않는지 확인합니다."""
    request = page.context.request
    token_a = register_and_login(request, e2e_target, _account(e2e_account, "i02a"))
    token_b = register_and_login(request, e2e_target, _account(e2e_secondary_account, "i02b"))
    owner_chat = api_post(
        request, e2e_target, "/api/chat", {"question": "E2E 소유자 기록"}, token_b
    )
    assert owner_chat.status == 200
    conversation_id = owner_chat.json()["conversation_id"]
    count_a = len(chat_history(request, e2e_target, token_a))
    count_b = len(chat_history(request, e2e_target, token_b))
    denied = api_post(
        request,
        e2e_target,
        "/api/chat",
        {"question": "E2E 타인 대화 접근", "conversation_id": conversation_id},
        token_a,
    )
    assert denied.status == 404
    assert len(chat_history(request, e2e_target, token_a)) == count_a
    assert len(chat_history(request, e2e_target, token_b)) == count_b
    e2e_record("I02", request_id=response_request_id(denied), status=denied.status, history_count=count_a + count_b)


@pytest.mark.e2e_scenario("A02")
@pytest.mark.deployment_only
def test_a02_expired_token_clears_session_and_preserves_draft(
    page: Page,
    e2e_target: str,
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """1분 JWT 만료 뒤 401·토큰 제거·질문 보존·저장 불변을 확인합니다."""
    account = _account(e2e_secondary_account, "a02")
    register_account(
        page.context.request,
        e2e_target,
        account["username"],
        account["password"],
    )
    page.goto(e2e_target)
    page.get_by_role("button", name="로그인").click()
    page.locator("#login-username").fill(account["username"])
    page.locator("#login-password").fill(account["password"])
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/auth/login")
    ) as login_response:
        page.locator("#login-submit-button").click()
    assert login_response.value.status == 200
    token = page.evaluate("localStorage.getItem('access_token')")
    assert isinstance(token, str) and token
    first_question = "E2E JWT 만료 전 저장 " + os.environ.get("E2E_RUN_ID", "run")
    page.locator("#question-input").fill(first_question)
    wait_for_gemini_slot()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/chat")
    ) as first_chat:
        page.locator("#send-button").click()
    assert first_chat.value.status == 200
    before_expiry_count = len(chat_history(page.context.request, e2e_target, token))
    page.wait_for_timeout(65_000)
    expired_question = "E2E JWT 만료 후 입력 보존"
    page.locator("#question-input").fill(expired_question)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/chat")
    ) as expired_chat:
        page.locator("#send-button").click()
    response = expired_chat.value
    assert response.status == 401
    expect(page.locator("#auth-modal")).to_be_visible()
    expect(page.locator("#auth-notice")).to_contain_text("다시 로그인")
    assert page.evaluate("localStorage.getItem('access_token')") is None
    assert page.locator("#question-input").input_value() == expired_question
    refreshed_token = login_account(
        page.context.request,
        e2e_target,
        account["username"],
        account["password"],
    )
    assert len(chat_history(page.context.request, e2e_target, refreshed_token)) == before_expiry_count
    e2e_record("A02", request_id=response_request_id(response), status=response.status, history_count=before_expiry_count)


@pytest.mark.e2e_scenario("I04")
@pytest.mark.deployment_only
def test_i04_outbound_context_contains_only_the_latest_five_pairs(
    page: Page,
    e2e_target: str,
    e2e_secondary_account: dict[str, str],
    e2e_record,
):
    """실제 Gemini 전송 문맥의 역할 순서와 최근 다섯 쌍 해시를 준비합니다."""
    expected_path = os.environ.get("E2E_CONTEXT_EXPECTED_FILE", "")
    assert expected_path, "문맥 관측 결과 파일 경로가 없습니다."
    account = _account(e2e_secondary_account, "i04")
    token = register_and_login(page.context.request, e2e_target, account)
    conversation_id = None
    for turn in range(6):
        question = f"E2E 문맥 순서 질문 {turn} {os.environ.get('E2E_RUN_ID', 'run')}"
        response = api_post(
            page.context.request,
            e2e_target,
            "/api/chat",
            {"question": question, **({"conversation_id": conversation_id} if conversation_id else {})},
            token,
        )
        assert response.status == 200
        payload = response.json()
        conversation_id = payload["conversation_id"]
    history_rows = [
        row
        for row in chat_history(page.context.request, e2e_target, token)
        if row["conversation_id"] == conversation_id
    ]
    history_rows.sort(key=lambda row: row["chat_log_id"])
    assert len(history_rows) == 6
    current_question = "E2E 문맥 최근 다섯 쌍 확인 " + os.environ.get("E2E_RUN_ID", "run")
    expected = []
    for row in history_rows[-5:]:
        expected.extend(
            [
                {"role": "user", "sha256": sha256_text(row["question"])},
                {"role": "model", "sha256": sha256_text(row["response"])},
            ]
        )
    expected.append({"role": "user", "sha256": sha256_text(current_question)})
    response = api_post(
        page.context.request,
        e2e_target,
        "/api/chat",
        {"question": current_question, "conversation_id": conversation_id},
        token,
    )
    assert response.status == 200
    with open(expected_path, "w", encoding="utf-8", newline="\n") as output:
        json.dump(expected, output, separators=(",", ":"))
        output.write("\n")
    e2e_record(
        "I04",
        request_id=response_request_id(response),
        status=response.status,
        conversation_id=conversation_id,
        history_count=len(expected),
    )
