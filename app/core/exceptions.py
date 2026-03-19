from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class NotFoundError(Exception):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str = "Resource", id: str | None = None):
        self.resource = resource
        self.id = id
        detail = f"{resource} not found"
        if id:
            detail = f"{resource} with id '{id}' not found"
        self.detail = detail
        super().__init__(self.detail)


class ValidationError(Exception):
    """Raised when input validation fails beyond Pydantic checks."""

    def __init__(self, detail: str = "Validation error"):
        self.detail = detail
        super().__init__(self.detail)


class AIServiceError(Exception):
    """Raised when an AI provider service call fails."""

    def __init__(self, detail: str = "AI service error", provider: str | None = None):
        self.detail = detail
        self.provider = provider
        super().__init__(self.detail)


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on the FastAPI app."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": exc.detail},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.detail},
        )

    @app.exception_handler(AIServiceError)
    async def ai_service_error_handler(
        request: Request, exc: AIServiceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": exc.detail, "provider": exc.provider},
        )
