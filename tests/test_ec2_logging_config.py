"""EC2 Nginx 로그 설정 스크립트의 보안 계약을 검증합니다."""

import re
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ec2"
    / "configure_nginx_logs.sh"
)


def test_access_log_excludes_query_and_request_headers():
    """접근 로그가 쿼리·Referer 대신 요청 경로와 처리 결과만 기록하는지 확인합니다."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    format_line = next(
        line for line in source.splitlines()
        if "log_format b7_1_request_trace" in line
    )

    assert "$request_method" in format_line
    assert "$uri" in format_line
    assert "$server_protocol" in format_line
    assert "$upstream_http_x_request_id" in format_line
    assert "$request_id" in format_line
    assert "$request_uri" not in format_line
    assert "$args" not in format_line
    assert "$http_referer" not in format_line
    assert "$http_user_agent" not in format_line
    assert re.search(r"(?<![A-Za-z_])\$request(?![A-Za-z_])", format_line) is None


def test_script_verifies_request_ids_and_blocked_log_paths():
    """적용 후 요청 ID 연결과 주요 로그 경로의 404 응답을 확인하는지 검증합니다."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'tolower($1) == "x-request-id:"' in source
    assert 'request_id=${APP_REQUEST_ID}' in source
    assert "nginx_request_id=[[:xdigit:]]{32}" in source
    assert "${QUERY_PROBE}" in source
    for path in (
        "/logs",
        "/logs/",
        "/logs/app.log",
        "/logs/app.log.1",
        "/logs/server.log",
        "/logs/nginx_access.log",
    ):
        assert path in source
