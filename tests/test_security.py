"""
Unit tests for pre-request security validation.
No network calls — all checks are on URL strings and resolved IPs.
"""
import pytest
from collector.crawler.security import (
    SecurityViolation,
    check_url,
    check_content_length,
    normalize_url,
    is_high_entropy_url,
)


# --- check_url: scheme validation ---

def test_http_url_passes():
    check_url("http://example.com/page.html")  # Should not raise


def test_https_url_passes():
    check_url("https://example.com/page.html")  # Should not raise


def test_file_scheme_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("file:///etc/passwd")
    assert exc.value.threat_type == "redirect_violation"


def test_gopher_scheme_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("gopher://example.com/")
    assert exc.value.threat_type == "redirect_violation"


def test_ftp_scheme_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("ftp://example.com/file.txt")
    assert exc.value.threat_type == "redirect_violation"


# --- check_url: Docker hostname SSRF ---

def test_docker_db_hostname_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://db:5432/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_docker_redis_hostname_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://redis:6379/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_docker_api_hostname_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://api:8000/admin")
    assert exc.value.threat_type == "ssrf_attempt"


# --- check_url: private IP SSRF ---

def test_loopback_ip_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://127.0.0.1/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_private_class_a_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://10.0.0.1/")
    assert exc.value.threat_type == "ssrf_attempt"


def test_private_class_c_rejected():
    with pytest.raises(SecurityViolation) as exc:
        check_url("http://192.168.1.100/")
    assert exc.value.threat_type == "ssrf_attempt"


# --- check_content_length ---

def test_content_length_within_limit_passes():
    check_content_length(1024, 5 * 1024 * 1024)  # Should not raise


def test_content_length_exceeds_limit_raises():
    with pytest.raises(SecurityViolation) as exc:
        check_content_length(10 * 1024 * 1024, 5 * 1024 * 1024)
    assert exc.value.threat_type == "oversized_response"


def test_none_content_length_passes():
    check_content_length(None, 5 * 1024 * 1024)  # Should not raise


# --- normalize_url ---

def test_normalize_strips_session_param():
    url = "http://example.com/page.html?sid=abc123&color=blue"
    result = normalize_url(url)
    assert "sid" not in result
    assert "color=blue" in result


def test_normalize_strips_utm_params():
    url = "http://example.com/page.html?utm_source=google&page=2"
    result = normalize_url(url)
    assert "utm_source" not in result
    assert "page=2" in result


def test_normalize_strips_phpsessid():
    url = "http://example.com/page.php?PHPSESSID=abc123def456"
    result = normalize_url(url)
    assert "PHPSESSID" not in result


def test_normalize_preserves_clean_url():
    url = "http://example.com/fish/tanks.html"
    assert normalize_url(url) == url


# --- is_high_entropy_url ---

def test_high_entropy_uuid_detected():
    url = "http://example.com/page?token=a3f9b12c4e5d6f7a8b9c0d1e2f3a4b5c"
    assert is_high_entropy_url(url) is True


def test_clean_url_not_high_entropy():
    assert is_high_entropy_url("http://example.com/fish.html?page=2") is False


def test_no_query_string_not_high_entropy():
    assert is_high_entropy_url("http://example.com/fish.html") is False
