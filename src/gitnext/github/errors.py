"""Stable error kinds shared by the Python SDK and CLI."""

from __future__ import annotations

from typing import Literal

GitHubErrorKind = Literal["INPUT", "NOT_FOUND", "FORBIDDEN", "RATE_LIMIT", "NETWORK", "INVALID_RESPONSE", "INTERNAL"]


class GitHubInputError(ValueError):
    kind: Literal["INPUT"] = "INPUT"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GitHubAccessError(RuntimeError):
    def __init__(self, kind: GitHubErrorKind, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


def classify_github_error(error: BaseException) -> GitHubAccessError:
    if isinstance(error, GitHubAccessError):
        return error
    raw_status = getattr(error, "status", None)
    if raw_status is None:
        response = getattr(error, "response", None)
        raw_status = getattr(response, "status_code", None)
    status = raw_status if isinstance(raw_status, int) else None
    message = str(error) or "GitHub request failed"
    if status in {401, 403}:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {})
        response_text = getattr(response, "text", "")
        rate_limited = (
            "rate limit" in message.lower()
            or (isinstance(response_text, str) and "rate limit" in response_text.lower())
            or getattr(headers, "get", lambda _key: None)("x-ratelimit-remaining") == "0"
        )
        return GitHubAccessError(
            "RATE_LIMIT" if rate_limited else "FORBIDDEN",
            "GitHub rate limit exceeded" if rate_limited else "GitHub access denied",
            status,
        )
    if status == 404:
        return GitHubAccessError("NOT_FOUND", "GitHub resource not found or inaccessible", status)
    if status is not None:
        return GitHubAccessError("NETWORK", f"GitHub request failed with status {status}", status)
    return GitHubAccessError("NETWORK", message)
