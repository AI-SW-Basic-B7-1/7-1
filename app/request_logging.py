"""HTTP 요청의 추적 번호와 처리 결과를 기록하는 미들웨어."""

from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logger import app_logger, request_id_context


class RequestLoggingMiddleware:
    """요청별 문맥을 격리하고 응답 본문 전송까지의 시간을 기록합니다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = request_id_context.set(request_id)
        started = perf_counter()
        method = scope["method"]
        path = scope["path"].replace("\r", "\\r").replace("\n", "\\n")
        status_code = 500

        async def send_response(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        app_logger.info("http_request_started method=%s path=%s", method, path)
        try:
            await self.app(scope, receive, send_response)
        except Exception:
            state["request_error_logged"] = True
            app_logger.exception(
                "http_request_failed method=%s path=%s status_code=%s duration_ms=%s",
                method, path, status_code, round((perf_counter() - started) * 1000),
            )
            raise
        else:
            app_logger.info(
                "http_request_completed method=%s path=%s status_code=%s duration_ms=%s",
                method, path, status_code, round((perf_counter() - started) * 1000),
            )
        finally:
            request_id_context.reset(token)
