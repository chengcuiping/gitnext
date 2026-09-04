"""Strict parser for supported public GitHub item URLs."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from gitnext.domain.facts import Source
from gitnext.github.errors import GitHubInputError

SEGMENT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def parse_github_url(input_url: str) -> Source:
    try:
        url = urlsplit(input_url)
        if not url.scheme or not url.netloc:
            raise ValueError
        port = url.port
    except (TypeError, ValueError) as error:
        raise GitHubInputError("INVALID_URL", "Input must be an absolute URL") from error
    if url.scheme != "https":
        raise GitHubInputError("INVALID_PROTOCOL", "Only HTTPS URLs are accepted")
    if url.hostname != "github.com":
        raise GitHubInputError("UNSUPPORTED_HOST", "Only github.com is supported")
    if url.username is not None or url.password is not None:
        raise GitHubInputError("CREDENTIALS_FORBIDDEN", "URL credentials are forbidden")
    # WHATWG URL normalizes an explicit default HTTPS port away; match that behavior.
    if port not in {None, 443}:
        raise GitHubInputError("PORT_FORBIDDEN", "Explicit ports are forbidden")

    segments = [segment for segment in url.path.split("/") if segment]
    if len(segments) != 4:
        raise GitHubInputError("INVALID_PATH", "Expected /OWNER/REPO/pull|issues/NUMBER")
    owner, repo, resource, number_text = segments
    if not SEGMENT.fullmatch(owner) or not SEGMENT.fullmatch(repo) or repo in {".", ".."}:
        raise GitHubInputError("INVALID_REPOSITORY", "Owner or repository is invalid")
    if resource not in {"pull", "issues"}:
        raise GitHubInputError("INVALID_KIND", "Resource must be pull or issues")
    if not re.fullmatch(r"[1-9]\d*", number_text):
        raise GitHubInputError("INVALID_NUMBER", "Resource number must be a positive integer")
    number = int(number_text)
    if number > MAX_SAFE_INTEGER:
        raise GitHubInputError("INVALID_NUMBER", "Resource number is too large")
    kind = "PULL_REQUEST" if resource == "pull" else "ISSUE"
    return Source.model_validate(
        {
            "originalUrl": input_url,
            "canonicalUrl": f"https://github.com/{owner}/{repo}/{resource}/{number}",
            "owner": owner,
            "repo": repo,
            "number": number,
            "kind": kind,
        }
    )
