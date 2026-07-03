from __future__ import annotations


class AppError(Exception):
    """Base application exception with HTTP metadata."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigurationError(AppError):
    status_code = 500
    error_code = "configuration_error"


class AIServiceError(AppError):
    status_code = 502
    error_code = "ai_service_error"


class DataAccessError(AppError):
    status_code = 500
    error_code = "data_access_error"


class BadRequestError(AppError):
    status_code = 400
    error_code = "bad_request"


class NewsServiceError(AppError):
    status_code = 503
    error_code = "news_service_error"
