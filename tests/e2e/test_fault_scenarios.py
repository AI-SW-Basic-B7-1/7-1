"""실제 배포에서만 주입하는 장애와 사용자 화면 반응을 확인합니다."""

import json
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    chat_history,
    login_account,
    response_request_id,
    sha256_text,
    verify_visible_records,
    wait_for_gemini_slot,
)


def _history_fingerprint(rows: list[dict]) -> list[tuple[int, str, str]]:
    """대화 원문 없이 저장 행의 식별자와 해시만 반환합니다."""
    from tests.e2e.helpers import sha256_text

    return sorted(
        (
            row["chat_log_id"],
            sha256_text(row["question"]),
            sha256_text(row["response"]),
        )
        for row in rows
    )


def _submit_question(page: Page, question: str):
    """실제 화면에서 한 질문을 전송하고 응답 객체만 반환합니다."""
    page.locator("#question-input").fill(question)
    wait_for_gemini_slot()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/chat")
    ) as response_info:
        page.locator("#send-button").click()
    expect(page.locator("#send-button")).to_be_enabled(timeout=15000)
    return response_info.value


def _login(page: Page, target: str, account: dict[str, str]) -> str:
    """기존 시험 계정으로 로그인하고 토큰을 반환합니다."""
    page.goto(target)
    page.get_by_role("button", name="로그인").click()
    page.locator("#login-username").fill(account["username"])
    page.locator("#login-password").fill(account["password"])
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/auth/login")
    ) as response_info:
        page.locator("#login-submit-button").click()
    assert response_info.value.status == 200
    expect(page.get_by_role("button", name="로그아웃")).to_be_visible()
    return login_account(
        page.context.request,
        target,
        account["username"],
        account["password"],
    )


@pytest.mark.deployment_only
@pytest.mark.e2e_scenario("F01")
def test_f01_gemini_upstream_error_returns_502(
    page: Page, e2e_target: str, e2e_account: dict[str, str], e2e_record
):
    """존재하지 않는 모델 오류가 502와 안전한 화면 안내로 연결되는지 확인합니다."""
    token = _login(page, e2e_target, e2e_account)
    before = _history_fingerprint(chat_history(page.context.request, e2e_target, token))
    started = time.perf_counter()
    response = _submit_question(page, "E2E 제어된 Gemini 오류 확인")
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    assert response.status == 502
    expect(page.locator(".message-row-assistant.is-error .message-text").last).to_contain_text(
        "AI 응답을 생성하지 못했습니다"
    )
    after = _history_fingerprint(chat_history(page.context.request, e2e_target, token))
    assert after == before, "AI 실패 뒤 저장 대화가 추가되거나 변경되었습니다."
    e2e_record("F01", request_id=response_request_id(response), status=502, elapsed_ms=elapsed_ms)


@pytest.mark.deployment_only
@pytest.mark.e2e_scenario("F02")
def test_f02_delayed_https_proxy_returns_504(
    page: Page, e2e_target: str, e2e_account: dict[str, str], e2e_record
):
    """루프백 HTTPS 지연이 HTTPX 제한 시간과 504 안내로 연결되는지 확인합니다."""
    token = _login(page, e2e_target, e2e_account)
    before = _history_fingerprint(chat_history(page.context.request, e2e_target, token))
    started = time.perf_counter()
    response = _submit_question(page, "E2E 제어된 네트워크 지연 확인")
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    assert response.status == 504
    expect(page.locator(".message-row-assistant.is-error .message-text").last).to_contain_text(
        "AI 응답이 지연되고 있습니다"
    )
    after = _history_fingerprint(chat_history(page.context.request, e2e_target, token))
    assert after == before, "AI 시간 초과 뒤 저장 대화가 추가되거나 변경되었습니다."
    e2e_record("F02", request_id=response_request_id(response), status=504, elapsed_ms=elapsed_ms)


@pytest.mark.deployment_only
@pytest.mark.e2e_scenario("F03")
def test_f03_database_read_denial_returns_500_without_ai_call(
    page: Page, e2e_target: str, e2e_account: dict[str, str], e2e_state, e2e_record
):
    """SQLite 대화 읽기 거부가 이력·채팅 500으로 이어지는지 확인합니다."""
    token = _login(page, e2e_target, e2e_account)
    history = page.context.request.get(
        f"{e2e_target}/api/me/chats",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    assert history.status == 500
    state = e2e_state["read"]()
    assert isinstance(state.get("conversation_id"), int), "기존 대화방 기준 자료가 없습니다."

    def retain_existing_conversation(route):
        payload = route.request.post_data_json
        assert isinstance(payload, dict)
        payload["conversation_id"] = state["conversation_id"]
        headers = dict(route.request.headers)
        headers["content-type"] = "application/json"
        route.continue_(post_data=json.dumps(payload), headers=headers)

    page.route("**/api/chat", retain_existing_conversation)
    response = _submit_question(page, "E2E 제어된 DB 읽기 오류 확인")
    page.unroute("**/api/chat", retain_existing_conversation)
    assert response.status == 500
    expect(page.locator(".message-row-assistant.is-error .message-text").last).to_contain_text(
        "대화 기록을 불러오지 못했습니다"
    )
    e2e_record("F03", request_id=response_request_id(response), status=500)
    e2e_record("F03", request_id=response_request_id(history), status=500)


@pytest.mark.deployment_only
@pytest.mark.e2e_scenario("F04")
def test_f04_database_write_denial_rolls_back_partial_chat(
    page: Page, e2e_target: str, e2e_account: dict[str, str], e2e_record
):
    """SQLite 대화 삽입 거부가 500을 반환하고 기록을 남기지 않는지 확인합니다."""
    token = _login(page, e2e_target, e2e_account)
    before = _history_fingerprint(chat_history(page.context.request, e2e_target, token))
    page.locator("#new-question-button").click()
    question = "E2E 제어된 DB 저장 오류 확인"
    page.locator("#question-input").fill(question)
    wait_for_gemini_slot()
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/api/chat")
    ) as request_info:
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/chat")
        ) as response_info:
            page.locator("#send-button").click()
    payload = request_info.value.post_data_json
    assert isinstance(payload, dict) and "conversation_id" not in payload
    response = response_info.value
    assert response.status == 500
    expect(page.locator(".message-row-assistant.is-error .message-text").last).to_contain_text(
        "대화 기록을 저장하지 못했습니다"
    )
    after = _history_fingerprint(chat_history(page.context.request, e2e_target, token))
    assert after == before, "DB 저장 실패 뒤 부분 대화가 남았습니다."
    e2e_record("F04", request_id=response_request_id(response), status=500)


@pytest.mark.deployment_only
@pytest.mark.e2e_scenario("F05")
def test_f05_restored_service_saves_and_restores_a_normal_chat(
    browser, e2e_target: str, e2e_account: dict[str, str], e2e_state, e2e_record
):
    """임시 장애 설정을 제거한 뒤 정상 Gemini 채팅을 저장하고 다시 조회합니다."""
    state = e2e_state["read"]()
    assert state.get("records"), "복원 후 확인할 기존 대화 기준 자료가 없습니다."
    context = browser.new_context()
    try:
        page = context.new_page()
        token = _login(page, e2e_target, e2e_account)
        rows = chat_history(context.request, e2e_target, token)
        for expected in state["records"]:
            assert any(
                row["conversation_id"] == state["conversation_id"]
                and sha256_text(row["question"]) == expected["question_sha256"]
                and sha256_text(row["response"]) == expected["answer_sha256"]
                for row in rows
            ), "복원 뒤 기존 대화 기록을 API에서 찾지 못했습니다."
        conversation = page.locator(
            f'.conversation-button[data-conversation-id="{state["conversation_id"]}"]'
        )
        expect(conversation).to_be_visible()
        conversation.click()
        verify_visible_records(page, state["records"])
        question = "E2E 장애 복원 후 정상 채팅 확인"
        question_hash = sha256_text(question)
        response = _submit_question(page, question)
        assert response.status == 200
        request_id = response_request_id(response)
        after = chat_history(context.request, e2e_target, token)
        saved = next(
            (
                row
                for row in after
                if row["conversation_id"] == state["conversation_id"]
                and sha256_text(row["question"]) == question_hash
            ),
            None,
        )
        assert saved is not None, "복원 후 질문이 DB 이력에 없습니다."
        answer_hash = sha256_text(saved["response"])
        state["records"].append(
            {
                "question_sha256": question_hash,
                "answer_sha256": answer_hash,
                "request_id": request_id,
            }
        )
        e2e_state["write"](state)
        verify_visible_records(page, state["records"])
        e2e_record(
            "F05",
            request_id=request_id,
            status=200,
            conversation_id=saved["conversation_id"],
            question_sha256=question_hash,
            answer_sha256=answer_hash,
        )
    finally:
        context.close()
