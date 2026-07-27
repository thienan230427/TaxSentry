from __future__ import annotations

import re

_SECRETS = (
    re.compile(
        r"(?i)\b(?:api[_ -]?key|password|passwd|token|secret|authorization|app[_ -]?password)"
        r"\b\s*[:=]\s*[^\r\n]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)


def contains_secret(content: str) -> bool:
    return any(pattern.search(content) for pattern in _SECRETS)


def redact_secrets(content: str) -> str:
    for pattern in _SECRETS:
        content = pattern.sub("[REDACTED]", content)
    return content
