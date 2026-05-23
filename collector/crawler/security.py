"""
Pre-request security validation.
All checks run BEFORE any HTTP request is made.
Any violation raises SecurityViolation, which the worker catches and logs to threat_log.
"""
from __future__ import annotations
import ipaddress
import re
import socket
from urllib.parse import urlparse, urlencode, parse_qsl

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_DOCKER_HOSTNAMES = frozenset({"db", "redis", "api", "crawler", "celery"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})

_SESSION_PARAM = re.compile(
    r'^(session|sid|phpsessid|jsessionid|token|csrf|utm_|fbclid|gclid)',
    re.IGNORECASE,
)
_HIGH_ENTROPY_VALUE = re.compile(r'^[a-f0-9\-]{20,}$', re.IGNORECASE)


class SecurityViolation(Exception):
    def __init__(self, threat_type: str, detail: str) -> None:
        self.threat_type = threat_type
        self.detail = detail
        super().__init__(f"[{threat_type}] {detail}")


def check_url(url: str) -> None:
    """
    Validate URL before making any request.
    Raises SecurityViolation on any check failure.
    Order: scheme → Docker hostname → IP range.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SecurityViolation(
            "redirect_violation",
            f"Disallowed scheme '{parsed.scheme}' in URL: {url}",
        )

    hostname = parsed.hostname
    if not hostname:
        raise SecurityViolation("redirect_violation", f"No hostname in URL: {url}")

    if hostname in _DOCKER_HOSTNAMES:
        raise SecurityViolation(
            "ssrf_attempt",
            f"Docker service hostname '{hostname}' in URL: {url}",
        )

    # Resolve hostname → IP and check against private ranges
    try:
        resolved = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(resolved)
        for network in _PRIVATE_NETWORKS:
            if ip in network:
                raise SecurityViolation(
                    "ssrf_attempt",
                    f"Resolved IP {ip} for '{hostname}' is in private range {network}",
                )
    except (socket.gaierror, ValueError):
        pass  # Unresolvable hostname — let httpx handle the error naturally


def check_content_length(content_length: int | None, limit: int) -> None:
    """Raise SecurityViolation if Content-Length header exceeds limit."""
    if content_length is not None and content_length > limit:
        raise SecurityViolation(
            "oversized_response",
            f"Content-Length {content_length:,} exceeds limit {limit:,}",
        )


def normalize_url(url: str) -> str:
    """
    Remove session/tracking query parameters to prevent spider traps
    and avoid indexing the same page under many different URLs.
    """
    parsed = urlparse(url)
    if not parsed.query:
        return url

    kept = [
        (k, v) for k, v in parse_qsl(parsed.query)
        if not _SESSION_PARAM.match(k)
    ]
    clean = parsed._replace(query=urlencode(kept))
    return clean.geturl()


def is_high_entropy_url(url: str) -> bool:
    """
    Detect potential spider trap: query parameter with a long, random-looking value
    (UUID, session token, etc.). Returns True if the URL looks like a trap.
    """
    parsed = urlparse(url)
    if not parsed.query:
        return False
    for _, value in parse_qsl(parsed.query):
        if len(value) > 20 and _HIGH_ENTROPY_VALUE.match(value):
            return True
    return False
