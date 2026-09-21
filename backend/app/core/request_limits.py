"""Bound request bodies before multipart/JSON parsing, including chunked uploads."""
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int = 24 * 1024 * 1024) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        length = dict(scope.get("headers", [])).get(b"content-length", b"0")
        try:
            too_large = int(length) > self.max_bytes
        except ValueError:
            too_large = True
        messages, total = [], 0
        while not too_large:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                too_large = True
                break
            messages.append(message)
            if not message.get("more_body", False):
                break
        if too_large:
            return await JSONResponse({"detail": "Request body exceeds the upload limit."}, status_code=413)(scope, receive, send)
        iterator = iter(messages)

        async def bounded_receive():
            message = next(iterator, None)
            return message if message is not None else await receive()

        await self.app(scope, bounded_receive, send)
