"""애플리케이션과 채팅 처리 과정의 표준 로깅 모듈.

본 모듈은 콘솔과 파일에 동일한 형식으로 서버 오류와 채팅 핵심 이벤트를 기록합니다.
"""

import logging
import re
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from app.config import LOG_DIR, LOG_FILE, settings

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class SensitiveDataFormatter(logging.Formatter):
    """메시지와 예외 체인을 포맷한 뒤 알려진 비밀값을 출력에서 가립니다."""

    def format(self, record: logging.LogRecord) -> str:
        output = super().format(record)
        secrets = (settings.SECRET_KEY, settings.GEMINI_API_KEY)
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            output = output.replace(secret, "[REDACTED]")
        output = re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer [REDACTED]",
            output,
        )
        output = re.sub(
            r'''(?i)(["']?\b(?:password|hashed_password|access_token|api_key|x-goog-api-key|secret_key)["']?\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s&,;]+)''',
            r"\1[REDACTED]",
            output,
        )
        return output


class RequestContextFilter(logging.Filter):
    """동시 요청의 로그에 해당 요청의 추적 번호를 추가합니다."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = request_id_context.get()
        record.request_suffix = (
            f" request_id={request_id}"
            if request_id and "request_id=" not in record.getMessage()
            else ""
        )
        return True


def get_app_logger() -> logging.Logger:
    """중복 핸들러 없이 애플리케이션 표준 로거를 생성합니다."""
    logger = logging.getLogger("app")
    if logger.handlers:
        return logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = SensitiveDataFormatter(
        "%(asctime)s %(levelname)s %(message)s%(request_suffix)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RequestContextFilter())

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RequestContextFilter())

    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


app_logger = get_app_logger()
chat_logger = app_logger.getChild("chat")
