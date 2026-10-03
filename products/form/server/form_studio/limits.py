from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class BodyLimit:
    """Enforce stream budget before multipart parsing/spooling, including chunked requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = (
            (130 * 1024 * 1024) if scope["path"].endswith("/uploads") else 128 * 1024
        )
        size = 0

        async def bounded_receive():
            nonlocal size
            value = await receive()
            size += len(value.get("body", b""))
            if size > limit:
                raise BodyTooLarge()
            return value

        try:
            await self.app(scope, bounded_receive, send)
        except BodyTooLarge:
            await JSONResponse(
                {"detail": "Request stream exceeds budget."}, status_code=413
            )(scope, receive, send)
