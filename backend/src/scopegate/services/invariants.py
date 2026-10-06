"""Explicit required-row checks for database results guaranteed by the use case."""

from scopegate import db
from scopegate.errors import AppError


def required_row(conn, sql: str, parameters: dict | None = None) -> dict:
    value = db.row(conn, sql, parameters)
    if value is None:
        raise AppError(500, "integrity_error", "A required internal record is unavailable.")
    return value
