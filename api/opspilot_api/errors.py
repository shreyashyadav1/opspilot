"""Errors that map to HTTP responses."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(
        self, status_code: int, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
