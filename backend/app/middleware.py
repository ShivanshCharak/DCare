"""ASGI middleware for request-size limits and optional API access control."""

import hmac

from starlette.responses import JSONResponse


class RequestBodyTooLarge(Exception):
    pass


class MaxRequestBodySize:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header."},
                )
                await response(scope, receive, send)
                return
            if declared_size < 0:
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header."},
                )
                await response(scope, receive, send)
                return
            if declared_size > self.max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body exceeds {self.max_bytes} bytes."},
                )
                await response(scope, receive, send)
                return

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if not response_started:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body exceeds {self.max_bytes} bytes."},
                )
                await response(scope, receive, send)


class BearerTokenAuth:
    """Require a shared bearer token when configured or in production mode."""

    def __init__(self, app, api_access_token: str = "", app_env: str = "development"):
        self.app = app
        self.api_access_token = api_access_token
        self.production = app_env.casefold() == "production"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return

        if not self.api_access_token:
            if not self.production:
                await self.app(scope, receive, send)
                return
            response = JSONResponse(
                status_code=503,
                content={"detail": "API access token is not configured."},
            )
            await response(scope, receive, send)
            return

        authorization = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"authorization"
            ),
            b"",
        ).decode("latin-1")
        scheme, separator, supplied_token = authorization.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or not hmac.compare_digest(supplied_token, self.api_access_token)
        ):
            response = JSONResponse(
                status_code=401,
                content={"detail": "A valid bearer token is required."},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
