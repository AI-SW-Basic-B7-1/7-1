"""가입부터 로그인·채팅·이력 복원까지 브라우저에서 검증합니다."""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.browser_e2e
def test_register_chat_and_restore_history(
    page: Page,
    e2e_target: str,
    e2e_account: dict[str, str],
):
    """브라우저에서 저장된 질문과 답변을 로그아웃 후 다시 복원합니다."""
    page.goto(e2e_target)

    page.get_by_role("button", name="로그인").click()
    if os.environ.get("E2E_EXISTING_ACCOUNT") == "1":
        page.locator("#login-username").fill(e2e_account["username"])
        page.locator("#login-password").fill(e2e_account["password"])
        page.locator("#login-submit-button").click()
        expect(page.get_by_role("button", name="로그아웃")).to_be_visible()
        previous_conversation = page.locator(
            "#conversation-list .conversation-button"
        ).first
        expect(previous_conversation).to_be_visible(timeout=15000)
        previous_conversation.click()
        expect(page.locator(".message-row-user .message-text").first).to_contain_text(
            "테스트용 질문 " + e2e_account["username"]
        )
        previous_answer = page.locator(".message-row-assistant .message-text").first
        expect(previous_answer).to_be_visible()
        assert previous_answer.inner_text().strip()
    else:
        expect(page.locator("#auth-modal")).to_be_visible()
        page.locator("#show-register-button").click()
        page.locator("#register-username").fill(e2e_account["username"])
        page.locator("#register-password").fill(e2e_account["password"])
        page.locator("#register-submit-button").click()
        expect(page.locator("#auth-notice")).to_contain_text("회원가입이 완료되었습니다.")
        page.locator("#login-username").fill(e2e_account["username"])
        page.locator("#login-password").fill(e2e_account["password"])
        page.locator("#login-submit-button").click()
        expect(page.get_by_role("button", name="로그아웃")).to_be_visible()

    preserve_marker = os.environ.get("E2E_PRESERVE_CHAT_MARKER", "")
    question = (
        "E2E 배포 DB 보존 확인 " + preserve_marker
        if preserve_marker
        else (
            "배포 복구 확인 질문 " + e2e_account["username"]
            if os.environ.get("E2E_EXISTING_ACCOUNT") == "1"
            else "테스트용 질문 " + e2e_account["username"]
        )
    )
    page.locator("#question-input").fill(question)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/chat")
    ) as response_info:
        page.locator("#send-button").click()
    chat_response = response_info.value
    assert chat_response.status == 200
    request_id = chat_response.headers.get("x-request-id", "")
    assert re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        request_id,
    )
    evidence_path = os.environ.get("E2E_REQUEST_ID_FILE")
    if evidence_path:
        Path(evidence_path).write_text(request_id, encoding="utf-8")
    answer = page.locator(
        ".message-row-assistant:not(.is-pending):not(.is-error) .message-text"
    ).last
    expect(answer).to_be_visible(timeout=15000)
    response_payload = chat_response.json()
    expected_answer = response_payload["answer"].strip()
    assert expected_answer
    expect(answer).to_have_text(expected_answer, timeout=15000)

    page.get_by_role("button", name="로그아웃").click()
    expect(page.get_by_role("button", name="로그인")).to_be_visible()
    page.get_by_role("button", name="로그인").click()
    page.locator("#login-username").fill(e2e_account["username"])
    page.locator("#login-password").fill(e2e_account["password"])
    page.locator("#login-submit-button").click()
    expect(page.get_by_role("button", name="로그아웃")).to_be_visible()

    conversation = page.locator("#conversation-list .conversation-button").first
    expect(conversation).to_be_visible(timeout=15000)
    conversation.click()
    restored_question = page.locator(".message-row-user .message-text").last
    restored_answer = page.locator(".message-row-assistant .message-text").last
    expect(restored_question).to_have_text(question)
    expect(restored_answer).to_have_text(expected_answer)
