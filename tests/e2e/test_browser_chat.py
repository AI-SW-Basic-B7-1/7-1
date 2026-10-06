"""외부 HTTPS 브라우저에서 인증·채팅·기록 복원을 확인합니다."""

import json
import os
import time
from pathlib import Path
from secrets import token_hex

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.helpers import (
    api_get,
    chat_history,
    response_request_id,
    sha256_text,
    verify_visible_records,
    wait_for_gemini_slot,
)


def _sign_in(page: Page, target: str, account: dict[str, str]) -> None:
    """브라우저에서 테스트 계정으로 로그인합니다."""
    page.goto(target)
    if page.get_by_role("button", name="로그아웃").is_visible():
        return
    page.get_by_role("button", name="로그인").click()
    page.locator("#login-username").fill(account["username"])
    page.locator("#login-password").fill(account["password"])
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/auth/login")
    ) as login_response:
        page.locator("#login-submit-button").click()
    assert login_response.value.status == 200
    expect(page.get_by_role("button", name="로그아웃")).to_be_visible()
    expect(page.locator("#send-button")).to_be_enabled(timeout=15000)


def _verify_records(request, target: str, token: str, state: dict) -> list[dict]:
    """저장된 기록의 대화방·질문·답변 해시를 API 이력과 대조합니다."""
    rows = chat_history(request, target, token)
    for expected in state["records"]:
        match = next(
            (
                row
                for row in rows
                if row["conversation_id"] == state["conversation_id"]
                and sha256_text(row["question"]) == expected["question_sha256"]
                and sha256_text(row["response"]) == expected["answer_sha256"]
            ),
            None,
        )
        assert match is not None, "배포 후 보존되어야 할 질문·답변 기록이 없습니다."
    return rows


@pytest.mark.e2e_scenario("N01", "O01")
def test_n01_https_entry_and_static_assets(
    page: Page,
    e2e_target: str,
    e2e_mode: str,
    e2e_record,
):
    """HTTPS 진입·정적 자원·브라우저 실행 오류를 확인합니다."""
    page_errors: list[str] = []
    asset_statuses: list[int] = []
    page.on("pageerror", lambda error: page_errors.append(type(error).__name__))
    page.on(
        "response",
        lambda response: asset_statuses.append(response.status)
        if "/static/" in response.url
        else None,
    )
    start_url = e2e_target
    if e2e_mode == "deployment":
        start_url = "http://" + e2e_target.removeprefix("https://")
    response = page.goto(start_url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    assert page.url.startswith("https://") if e2e_mode == "deployment" else page.url.startswith("http://127.0.0.1:")
    expect(page.locator("#question-input")).to_be_visible()
    assert asset_statuses and all(status == 200 for status in asset_statuses)
    assert not page_errors, "브라우저 페이지 오류가 발생했습니다."
    if e2e_mode == "deployment":
        request = response.request
        chain = [request.url]
        while request.redirected_from is not None:
            request = request.redirected_from
            chain.append(request.url)
        assert any(url.startswith("http://") for url in chain)
        assert chain[0].startswith("https://")
    e2e_record("N01", status=response.status)


@pytest.mark.e2e_scenario("N02")
def test_n02_browser_register_and_login(
    page: Page,
    e2e_target: str,
    e2e_account: dict[str, str],
    e2e_record,
):
    """회원가입과 로그인 UI의 실제 HTTP 상태 및 로그인 상태를 확인합니다."""
    page.goto(e2e_target)
    page.get_by_role("button", name="로그인").click()
    if os.environ.get("E2E_EXISTING_ACCOUNT") == "1":
        page.locator("#login-username").fill(e2e_account["username"])
        page.locator("#login-password").fill(e2e_account["password"])
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/auth/login")
        ) as login_response:
            page.locator("#login-submit-button").click()
        assert login_response.value.status == 200
    else:
        page.locator("#show-register-button").click()
        page.locator("#register-username").fill(e2e_account["username"])
        page.locator("#register-password").fill(e2e_account["password"])
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/auth/register")
        ) as register_response:
            page.locator("#register-submit-button").click()
        assert register_response.value.status == 201
        expect(page.locator("#auth-notice")).to_contain_text("회원가입이 완료되었습니다.")
        page.locator("#login-username").fill(e2e_account["username"])
        page.locator("#login-password").fill(e2e_account["password"])
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/auth/login")
        ) as login_response:
            page.locator("#login-submit-button").click()
        assert login_response.value.status == 200
    expect(page.get_by_role("button", name="로그아웃")).to_be_visible()
    e2e_record("N02", status=login_response.value.status)


@pytest.mark.e2e_scenario("N03")
def test_n03_chat_response_and_preserved_database_records(
    page: Page,
    e2e_target: str,
    e2e_account: dict[str, str],
    e2e_state,
    e2e_record,
):
    """채팅 답변·브라우저·저장 이력을 해시로 연결하고 복구 뒤 기록을 확인합니다."""
    state = e2e_state["read"]()
    existing_account = os.environ.get("E2E_EXISTING_ACCOUNT") == "1"
    preserve_marker = os.environ.get("E2E_PRESERVE_CHAT_MARKER", "")
    _sign_in(page, e2e_target, e2e_account)
    if existing_account and not preserve_marker:
        assert state.get("records"), "복구 비교용 기준 해시 자료가 없습니다."
        token = page.evaluate("localStorage.getItem('access_token')") or ""
        rows = _verify_records(page.context.request, e2e_target, token, state)
        conversation = page.locator(
            f'.conversation-button[data-conversation-id="{state["conversation_id"]}"]'
        )
        expect(conversation).to_be_visible()
        conversation.click()
        verify_visible_records(page, state["records"])
        e2e_record("N03", status=200, conversation_id=state["conversation_id"], history_count=len(rows))
        return

    token = page.evaluate("localStorage.getItem('access_token')") or ""
    conversation_id = state.get("conversation_id") if preserve_marker else None
    if preserve_marker:
        assert state.get("records"), "보존 시험의 기존 대화 해시 자료가 없습니다."
        rows = _verify_records(page.context.request, e2e_target, token, state)
        conversation = page.locator(
            f'.conversation-button[data-conversation-id="{conversation_id}"]'
        )
        expect(conversation).to_be_visible()
        conversation.click()
        verify_visible_records(page, state["records"])
        question = "E2E 배포 DB 보존 확인 " + preserve_marker
    else:
        question = "E2E 배포 정상 확인 " + os.environ.get("E2E_RUN_ID", token_hex(6))

    page.locator("#question-input").fill(question)
    wait_for_gemini_slot()
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/api/chat")
    ) as chat_request_info:
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/chat")
        ) as chat_response_info:
            page.locator("#send-button").click()
    chat_request = chat_request_info.value
    payload = chat_request.post_data_json
    assert isinstance(payload, dict)
    if preserve_marker:
        assert payload.get("conversation_id") == conversation_id
    else:
        assert "conversation_id" not in payload
    response = chat_response_info.value
    assert response.status == 200
    request_id = response_request_id(response)
    result = response.json()
    saved_conversation_id = result.get("conversation_id")
    answer = result.get("answer", "").strip()
    assert isinstance(saved_conversation_id, int) and saved_conversation_id > 0
    assert conversation_id is None or saved_conversation_id == conversation_id
    assert answer
    visible_answer = page.locator(
        ".message-row-assistant:not(.is-pending):not(.is-error) .message-text"
    ).last
    deadline = time.monotonic() + 15
    visible_answer_hash = ""
    while time.monotonic() < deadline:
        visible_answer_hash = sha256_text(visible_answer.text_content() or "")
        if visible_answer_hash == sha256_text(answer):
            break
        page.wait_for_timeout(100)
    assert visible_answer_hash == sha256_text(answer), "화면 답변과 API 답변 해시가 일치하지 않습니다."

    updated_rows = chat_history(page.context.request, e2e_target, token)
    question_hash = sha256_text(question)
    answer_hash = sha256_text(answer)
    assert any(
        row["conversation_id"] == saved_conversation_id
        and sha256_text(row["question"]) == question_hash
        and sha256_text(row["response"]) == answer_hash
        for row in updated_rows
    ), "API 응답과 저장된 대화 해시가 일치하지 않습니다."

    if preserve_marker:
        state.setdefault("records", []).append(
            {
                "question_sha256": question_hash,
                "answer_sha256": answer_hash,
                "request_id": request_id,
            }
        )
        preserve_request_file = os.environ.get("E2E_PRESERVED_REQUEST_ID_FILE", "")
        if preserve_request_file:
            Path(preserve_request_file).write_text(request_id, encoding="utf-8")
    else:
        state = {
            "conversation_id": saved_conversation_id,
            "records": [
                {
                    "question_sha256": question_hash,
                    "answer_sha256": answer_hash,
                    "request_id": request_id,
                }
            ],
        }
    e2e_state["write"](state)
    verify_visible_records(page, state["records"])
    request_file = os.environ.get("E2E_REQUEST_ID_FILE", "")
    if request_file:
        Path(request_file).write_text(request_id, encoding="utf-8")
    e2e_record(
        "N03",
        request_id=request_id,
        status=response.status,
        conversation_id=saved_conversation_id,
        question_sha256=question_hash,
        answer_sha256=answer_hash,
        history_count=len(updated_rows),
    )


@pytest.mark.e2e_scenario("N04")
def test_n04_new_browser_context_restores_saved_records(
    browser: Browser,
    e2e_target: str,
    e2e_account: dict[str, str],
    e2e_state,
    e2e_record,
):
    """새 브라우저 컨텍스트에서 재로그인해 서버 저장 기록을 복원합니다."""
    state = e2e_state["read"]()
    assert state.get("records"), "새 컨텍스트 복원용 기준 해시 자료가 없습니다."
    context = browser.new_context()
    try:
        page = context.new_page()
        _sign_in(page, e2e_target, e2e_account)
        token = page.evaluate("localStorage.getItem('access_token')") or ""
        rows = _verify_records(page.context.request, e2e_target, token, state)
        conversation = page.locator(
            f'.conversation-button[data-conversation-id="{state["conversation_id"]}"]'
        )
        expect(conversation).to_be_visible()
        conversation.click()
        verify_visible_records(page, state["records"])
        e2e_record("N04", status=200, conversation_id=state["conversation_id"], history_count=len(rows))
    finally:
        context.close()


@pytest.mark.e2e_scenario("I03")
def test_i03_new_conversation_does_not_reuse_previous_context(
    page: Page,
    e2e_target: str,
    e2e_account: dict[str, str],
    e2e_state,
    e2e_record,
):
    """대화방을 바꿀 때 새 질문이 이전 대화방 식별자를 포함하지 않는지 확인합니다."""
    state = e2e_state["read"]()
    assert state.get("records"), "대화방 전환 기준 자료가 없습니다."
    _sign_in(page, e2e_target, e2e_account)
    page.locator(
        f'.conversation-button[data-conversation-id="{state["conversation_id"]}"]'
    ).click()
    page.locator("#new-question-button").click()
    question = "E2E 새 대화 분리 확인 " + os.environ.get("E2E_RUN_ID", token_hex(6))
    page.locator("#question-input").fill(question)
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/api/chat")
    ) as chat_request_info:
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/chat")
        ) as chat_response_info:
            page.locator("#send-button").click()
    payload = chat_request_info.value.post_data_json
    assert isinstance(payload, dict) and "conversation_id" not in payload
    response = chat_response_info.value
    assert response.status == 200
    request_id = response_request_id(response)
    new_conversation_id = response.json().get("conversation_id")
    assert isinstance(new_conversation_id, int) and new_conversation_id != state["conversation_id"]
    page.locator(
        f'.conversation-button[data-conversation-id="{state["conversation_id"]}"]'
    ).click()
    expect(page.locator("#send-button")).to_be_enabled(timeout=15000)
    visible_rows = page.locator(".message-row-user .message-text").all_inner_texts()
    assert any(sha256_text(text) == state["records"][0]["question_sha256"] for text in visible_rows)
    e2e_record("I03", request_id=request_id, status=response.status, conversation_id=new_conversation_id)
