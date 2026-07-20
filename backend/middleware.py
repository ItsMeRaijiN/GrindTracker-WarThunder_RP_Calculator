from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _contains_private_data(path: str) -> bool:
    return (
        path == "/api/auth"
        or path.startswith("/api/auth/")
        or path == "/api/progress"
        or path.startswith("/api/progress/")
    )


class RequestBodyTooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body is too large.")


class RequestSecurityMiddleware:
    def __init__(self, app: ASGIApp, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        response_started = False

        async def secure_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if path == "/" or path.startswith("/api/"):
                    headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                if scope.get("scheme") == "https":
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                if _contains_private_data(path):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        content_lengths = [value for name, value in scope.get("headers", []) if name.lower() == b"content-length"]
        if content_lengths:
            try:
                raw_length = content_lengths[0].decode("ascii")
                if len(content_lengths) != 1 or not raw_length.isdecimal():
                    raise ValueError
                content_length = int(raw_length)
            except (UnicodeDecodeError, ValueError):
                response = JSONResponse(status_code=400, content={"error": "Invalid Content-Length header."})
                await response(scope, receive, secure_send)
                return
            if content_length > self.max_request_bytes:
                response = JSONResponse(status_code=413, content={"error": "Request body is too large."})
                await response(scope, receive, secure_send)
                return

        received = 0

        async def receive_with_limit() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, receive_with_limit, secure_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            response = JSONResponse(status_code=413, content={"error": "Request body is too large."})
            await response(scope, receive, secure_send)
