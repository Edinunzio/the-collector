"""
Integration tests for the signal filter pipeline.
Tests the full score_page() function across all fixture pages.
"""
import pytest
from pathlib import Path
from collector.signals.filter import score_page, FilterResult

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_geocities_passes_filter():
    result = score_page(load("geocities_1999.html"), domain="fishluv99.example.com")
    assert result.passed is True
    assert result.score >= 3
    assert result.quarantine_reason is None


def test_geocities_has_expected_signals():
    result = score_page(load("geocities_1999.html"), domain="fishluv99.example.com")
    assert result.signals["no_framework"] == 2
    assert result.signals["old_html_elements"] >= 2
    assert result.signals["no_commercial_tracking"] == 2


def test_react_app_is_auto_rejected():
    result = score_page(load("react_app.html"), domain="myapp.example.com")
    assert result.passed is False
    assert result.auto_rejected is True


def test_jekyll_site_scores_low_due_to_ssg():
    result = score_page(load("jekyll_site.html"), domain="myblog.example.com")
    # SSG tag = -3, should suppress score
    assert result.signals["ssg_generator"] == -3


def test_frameset_page_goes_to_quarantine():
    result = score_page(load("frameset_page.html"), domain="oldsite.example.com")
    assert result.passed is False
    assert result.quarantine_reason == "frameset"
    assert result.auto_rejected is False  # Not rejected, quarantined for review


def test_borderline_page_goes_to_quarantine():
    result = score_page(load("borderline.html"), domain="example.com")
    # This page should score just under threshold
    assert result.passed is False
    # Either borderline_score or just rejected with score < threshold
    assert result.score < 3 or result.quarantine_reason == "borderline_score"


def test_noindex_page_auto_rejected():
    html = '<html><head><meta name="robots" content="noindex"></head><body><p>hi</p></body></html>'
    result = score_page(html, domain="example.com")
    assert result.passed is False
    assert result.auto_rejected is True


def test_empty_body_goes_to_quarantine():
    html = "<html><head><title>Empty</title></head><body>  </body></html>"
    result = score_page(html, domain="example.com")
    assert result.passed is False
    assert result.quarantine_reason == "empty_body"


def test_last_modified_header_boosts_score():
    html = load("jekyll_site.html")
    result_old = score_page(html, domain="example.com", last_modified="Mon, 01 Jan 2001 00:00:00 GMT")
    result_new = score_page(html, domain="example.com", last_modified=None)
    assert result_old.score > result_new.score


def test_filter_result_signals_dict_is_complete():
    """All expected signal keys must be present in result.signals."""
    expected_keys = {
        "no_framework", "small_page", "old_html_elements",
        "no_commercial_tracking", "no_cookie_consent", "no_jsonld",
        "hand_coded", "old_content_date", "asset_style",
        "ssg_generator", "modern_hosting",
    }
    result = score_page(load("geocities_1999.html"), domain="example.com")
    assert expected_keys.issubset(result.signals.keys())


def test_github_pages_domain_penalised():
    html = load("jekyll_site.html")
    result = score_page(html, domain="user.github.io")
    assert result.signals["modern_hosting"] == -2


def test_score_is_sum_of_signals():
    result = score_page(load("geocities_1999.html"), domain="example.com")
    assert result.score == sum(result.signals.values())
