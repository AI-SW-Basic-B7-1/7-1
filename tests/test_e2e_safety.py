"""E2E 대상 검증과 보고서의 최소 정보 정책을 확인합니다."""

import xml.etree.ElementTree as ET

import pytest

from scripts.e2e.compare_context_observation import read_context
from scripts.e2e.sanitize_junit_report import sanitize_report
from scripts.e2e.validate_junit_report import validate_report
from tests.e2e.conftest import E2EAccount, validate_e2e_target


def test_local_mode_rejects_a_remote_base_url():
    """로컬 테스트가 설정 실수로 배포 URL을 호출하지 않는지 확인합니다."""
    with pytest.raises(ValueError, match="deployment 모드"):
        validate_e2e_target("local", "https://example.test")


@pytest.mark.parametrize(
    "target",
    [
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test/path",
        "https://example.test:8443",
    ],
)
def test_deployment_mode_rejects_non_origin_urls(target: str):
    """배포 주소가 HTTPS 도메인 origin 외 정보를 포함하면 거부합니다."""
    with pytest.raises(ValueError):
        validate_e2e_target("deployment", target)


def test_account_representation_hides_credentials():
    """pytest 실패 요약의 계정 표현에서 자격 증명을 감춥니다."""
    account = E2EAccount(username="private-user", password="private-password")
    assert "private-user" not in repr(account)
    assert "private-password" not in str(account)


def test_junit_report_requires_scenario_properties_and_no_skip(tmp_path):
    """필수 시나리오가 JUnit에 있고 성공한 경우만 보고서를 인정합니다."""
    report = tmp_path / "report.xml"
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    case = ET.SubElement(suite, "testcase", name="test_n01[chromium]")
    properties = ET.SubElement(case, "properties")
    ET.SubElement(properties, "property", name="e2e_scenario", value="N01,O01")
    ET.ElementTree(root).write(report, encoding="utf-8", xml_declaration=True)
    assert validate_report(report, {"N01", "O01"})[0]

    ET.SubElement(case, "skipped")
    ET.ElementTree(root).write(report, encoding="utf-8", xml_declaration=True)
    valid, summary = validate_report(report, {"N01", "O01"})
    assert not valid and summary["skipped"] == 1


def test_junit_sanitizer_removes_credentials_tokens_and_raw_output(tmp_path):
    """실패 예시의 계정·JWT·원시 캡처를 보고서에서 지웁니다."""
    report = tmp_path / "unsafe.xml"
    report.write_text(
        '<testsuites><testsuite><testcase name="safe">'
        '<properties><property name="e2e_scenario" value="F01"/>'
        '<property name="account" value="private-user"/></properties>'
        '<failure message="password=private-password; account={\'username\': \'private-user\', \'password\': \'private-password\'}">'
        'Locator.fill("uncaptured-password"); AI answer is private answer'
        'Bearer abcdefghijklmnopqrstuvwxyz '
        'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature12345678'
        '</failure><system-out>private answer</system-out>'
        '</testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    sanitize_report(report, ["private-user", "private-password"])
    output = report.read_text(encoding="utf-8")
    assert "private-user" not in output
    assert "private-password" not in output
    assert "uncaptured-password" not in output
    assert "AI answer is private answer" not in output
    assert "'username': 'private-user'" not in output
    assert "'password': 'private-password'" not in output
    assert "private answer" not in output
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in output
    assert "eyJhbGciOiJIUzI1NiJ9" not in output
    assert 'name="e2e_scenario" value="F01"' in output


def test_junit_sanitizer_keeps_only_relative_failure_location(tmp_path):
    """Python traceback의 실패 위치만 보존하고 절대 경로와 상세를 지웁니다."""
    report = tmp_path / "failure-location.xml"
    report.write_text(
        '<testsuites><testsuite><testcase name="test_a02_expired_token_clears_session_and_preserves_draft[chromium]">'
        '<failure message="AssertionError: password=private-password">'
        'Traceback (most recent call last):\n'
        '  File "/home/runner/work/7-1/7-1/tests/e2e/test_api_scenarios.py", line 343, '
        'in test_a02_expired_token_clears_session_and_preserves_draft\n'
        'AssertionError: access_token=private-token'
        '</failure></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )

    sanitize_report(report, ["private-password", "private-token"])
    sanitize_report(report, ["private-password", "private-token"])
    output = report.read_text(encoding="utf-8")

    assert "tests/e2e/test_api_scenarios.py:343" in output
    assert "/home/runner" not in output
    assert "private-password" not in output
    assert "private-token" not in output
    assert "AssertionError: access_token=" not in output


def test_junit_sanitizer_rejects_fake_failure_location(tmp_path):
    """원문 속 가짜 파일 경로가 검증 위치로 남지 않는지 확인합니다."""
    report = tmp_path / "fake-location.xml"
    report.write_text(
        '<testsuites><testsuite><testcase name="test_a02_expired_token_clears_session_and_preserves_draft[chromium]">'
        '<failure message="AI answer contains tests/e2e/private-answer-fragment.py:42">'
        'Traceback (most recent call last):\n'
        '  File "/tmp/tests/e2e/private-answer-fragment.py", line 42, '
        'in test_a02_expired_token_clears_session_and_preserves_draft\n'
        'AI answer contains tests/e2e/private-answer-fragment.py:42'
        '</failure>'
        '<error message="AssertionError">'
        'Traceback (most recent call last):\n'
        '  File "/tmp/tests/e2e/test_api_scenarios.py", line 9999, '
        'in test_a02_expired_token_clears_session_and_preserves_draft\n'
        'AssertionError'
        '</error></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )

    sanitize_report(report, [])
    output = report.read_text(encoding="utf-8")

    assert "private-answer-fragment.py" not in output
    assert 'source_file="tests/e2e/private-answer-fragment.py"' not in output
    assert 'source_file="tests/e2e/test_api_scenarios.py"' not in output
    assert 'source_line="9999"' not in output
    assert "/tmp/" not in output
    assert "검증 위치:" not in output


def test_junit_sanitizer_reads_pytest_failure_location(tmp_path):
    """pytest JUnit의 파일·줄·예외 형식에서 실제 실패 위치를 보존합니다."""
    report = tmp_path / "pytest-failure-location.xml"
    report.write_text(
        '<testsuites><testsuite><testcase name="test_a02_expired_token_clears_session_and_preserves_draft[chromium]">'
        '<failure message="assert response.status == 401">'
        '&gt;       assert response.status == 401\n'
        'E       assert 200 == 401\n\n'
        'tests/e2e/test_api_scenarios.py:343: AssertionError'
        '</failure></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )

    sanitize_report(report, [])
    output = report.read_text(encoding="utf-8")

    assert 'source_file="tests/e2e/test_api_scenarios.py"' in output
    assert 'source_line="343"' in output
    assert "검증 위치: tests/e2e/test_api_scenarios.py:343" in output
    assert "assert 200 == 401" not in output


def test_junit_sanitizer_replaces_malformed_report_with_safe_failure(tmp_path):
    """정리할 수 없는 보고서 원문이 남지 않도록 안전한 실패 파일로 바꿉니다."""
    report = tmp_path / "truncated.xml"
    report.write_text("<testsuites>private-password", encoding="utf-8")
    with pytest.raises(ET.ParseError):
        sanitize_report(report, [])
    output = report.read_text(encoding="utf-8")
    assert "private-password" not in output
    assert "민감정보 보호를 위해 제거되었습니다" in output


def test_context_reader_rejects_raw_text(tmp_path):
    """문맥 증거 파일에 허용되지 않은 원문이 들어가면 거부합니다."""
    context = tmp_path / "context.json"
    context.write_text('[{"role":"user","text":"private"}]', encoding="utf-8")
    with pytest.raises(ValueError):
        read_context(context)
