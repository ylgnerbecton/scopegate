"""Stable safe errors for HTTP and operations."""


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str = "The operation could not be completed."):
        self.status = status
        self.status_code = status
        self.code = code
        self.message = message
        super().__init__(message)
