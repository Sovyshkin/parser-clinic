from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


def ensure_url(url: str) -> str:
    value = url.strip()
    if not value.lower().startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


def normalize_domain(url_or_domain: str) -> str:
    value = ensure_url(url_or_domain)
    host = (urlsplit(value).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def root_url(url_or_domain: str) -> str:
    value = ensure_url(url_or_domain)
    parts = urlsplit(value)
    domain = normalize_domain(value)
    scheme = parts.scheme if parts.scheme in {"http", "https"} else "https"
    port = parts.port
    netloc = f"{domain}:{port}" if port else domain
    return urlunsplit((scheme, netloc, "/", "", ""))


def normalize_phone(value: str) -> str | None:
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not 7 <= len(digits) <= 15:
        return None
    return f"+{digits}"


def normalize_email(value: str) -> str | None:
    email = value.strip().strip(".,;:()[]<>").lower()
    if re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", email, re.I):
        return email
    return None


def unique_sorted(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))
