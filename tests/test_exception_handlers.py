"""공통 예외 처리와 표준 로거 구성 회귀 테스트 모듈."""

import logging
import io
from logging.handlers import RotatingFileHandler
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.exception_handlers import ExceptionHandlerRegistrar
from app.logger import SensitiveDataFormatter, app_logger, chat_logger
from app.config import settings


def test_standard_logger_has_console_and_file_handlers():
    """표준 로거에 콘솔과 회전 파일 핸들러가 등록됐는지 확인합니다."""
    assert any(type(handler) is logging.StreamHandler for handler in app_logger.handlers)
    assert any(isinstance(handler, RotatingFileHandler) for handler in app_logger.handlers)
    assert chat_logger.parent is app_logger


def test_formatter_redacts_message_and_chained_traceback(monkeypatch):
    """콘솔·파일 포맷에서 비밀값을 가리고 예외 종류와 호출 경로는 유지합니다."""
    monkeypatch.setattr(settings, "SECRET_KEY", "test-signing-secret")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-provider-secret")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(SensitiveDataFormatter("%(message)s"))
    logger = logging.Logger("redaction-test")
    logger.addHandler(handler)
    try:
        try:
            raise ValueError("test-provider-secret Bearer private-token password='private password'")
        except ValueError as exc:
            raise RuntimeError('test-signing-secret {"access_token": "private-access"}') from exc
    except RuntimeError:
        logger.exception("test-provider-secret api_key=private-key request_id=trace-id")
    finally:
        handler.close()
    text = output.getvalue()
    for secret in (
        "test-signing-secret", "test-provider-secret", "private-token",
        "private password", "private-access", "private-key",
    ):
        assert secret not in text
    assert "Traceback" in text
    assert "ValueError" in text
    assert "RuntimeError" in text
    assert "request_id=trace-id" in text
    assert "[REDACTED]" in text
    configured_handlers = [
        handler for handler in app_logger.handlers
        if type(handler) is logging.StreamHandler or isinstance(handler, RotatingFileHandler)
    ]
    assert len(configured_handlers) == 2
    assert all(isinstance(handler.formatter, SensitiveDataFormatter) for handler in configured_handlers)


@pytest.mark.anyio
async def test_unhandled_exception_logs_traceback(monkeypatch):
    """미처리 예외가 사용자 메시지와 서버 오류 로그로 분리되는지 검증합니다."""
    registrar = ExceptionHandlerRegistrar(FastAPI())
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/test-error",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    exception_log = Mock()
    monkeypatch.setattr(app_logger, "exception", exception_log)

    response = await registrar.unhandled_exception_handler(
        request,
        RuntimeError("외부에 노출하면 안 되는 오류"),
    )

    assert response.status_code == 500
    assert response.body == '{"detail":"서버 내부 오류가 발생했습니다."}'.encode()
    exception_log.assert_called_once()
    assert exception_log.call_args.args[0] == (
        "unhandled_exception method=%s path=%s error=%s"
    )
