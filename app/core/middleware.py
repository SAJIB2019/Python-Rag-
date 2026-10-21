import logging
import re
import time
from uuid import uuid4

from starlette.responses import JSONResponse

logger = logging.getLogger("rag.http")


class RequestMiddleware:
    """Bound request bodies before multipart parsing, including chunked requests."""

    def __init__(self, app, settings, counter, histogram):
        self.app, self.settings = app, settings
        self.counter, self.histogram = counter, histogram

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        incoming_id = headers.get(b"x-request-id", b"").decode("latin1")
        request_id = (
            incoming_id if re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", incoming_id) else str(uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        start, status = time.monotonic(), 500

        async def send_response(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                ]
            await send(message)

        try:
            # Buffer only bounded bodies. The per-file cap is enforced again after parsing.
            upload = scope["path"].rstrip("/") == "/api/documents/upload"
            limit = (
                self.settings.upload_max_file_bytes + 65536
                if upload
                else self.settings.request_body_limit_bytes
            )
            messages, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                size += len(message.get("body", b""))
                if size > limit:
                    response = JSONResponse(
                        {
                            "statusCode": 413,
                            "message": "Request body is too large",
                            "path": scope["path"],
                        },
                        status_code=413,
                    )
                    await response(scope, receive, send_response)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break
            iterator = iter(messages)

            async def replay():
                try:
                    return next(iterator)
                except StopIteration:
                    return await receive()

            await self.app(scope, replay, send_response)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            elapsed = time.monotonic() - start
            self.counter.labels(scope["method"], route, str(status)).inc()
            self.histogram.labels(scope["method"], route).observe(elapsed)
            logger.info(
                "request_id=%s method=%s route=%s status=%s duration_ms=%.1f",
                request_id,
                scope["method"],
                route,
                status,
                elapsed * 1000,
            )
