"""Expected errors with safe public messages, independent of HTTP route handlers."""
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    detail: str


class ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ValidationErrorResponse(ErrorResponse):
    errors: list[ValidationIssue]


class ApiError(Exception):
    def __init__(self, code: str, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class DatabaseNotReady(ApiError):
    def __init__(self):
        super().__init__('database_not_ready',
            'The database is unavailable or needs an upgrade. Retry after it is ready.', 503)
