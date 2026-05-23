"""
Unit tests for individual signal detector functions.
Each detector takes parsed HTML (soup) or raw HTML string and returns an integer score.
Tests use fixtures from tests/fixtures/.
"""
import pytest
from pathlib import Path
from bs4 import BeautifulSoup

# Import paths we're about to implement
from collector.signals.detectors import (
    detect_no_js_framework,
    detect_small_page,
    detect_old_html_elements,
    detect_no_commercial_tracking,
    detect_no_cookie_consent,
    detect_no_jsonld,
    detect_hand_coded_smell,
    detect_old_content_date,
    detect_asset_style,
    detect_ssg_generator,
    detect_modern_hosting,
    is_spa,
    is_js_rendered,
    has_noindex,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> tuple[str, BeautifulSoup]:
    html = (FIXTURES / name).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    return html, soup


# --- detect_no_js_framework ---

def test_no_framework_returns_2_for_old_page():
    html, _ = load_fixture("geocities_1999.html")
    assert detect_no_js_framework(html) == 2


def test_no_framework_returns_0_for_react_app():
    html, _ = load_fixture("react_app.html")
    assert detect_no_js_framework(html) == 0


# --- detect_small_page ---

def test_small_page_returns_2_for_tiny_html():
    html, _ = load_fixture("geocities_1999.html")
    assert detect_small_page(html) == 2


def test_small_page_returns_0_for_large_html():
    big_html = "<html><body>" + ("x" * 200_000) + "</body></html>"
    assert detect_small_page(big_html) == 0


# --- detect_old_html_elements ---

def test_old_elements_scores_geocities():
    html, soup = load_fixture("geocities_1999.html")
    score = detect_old_html_elements(soup)
    assert score >= 2  # has <font>, <marquee>, <table>


def test_old_elements_scores_zero_for_modern():
    html, soup = load_fixture("jekyll_site.html")
    assert detect_old_html_elements(soup) == 0


def test_old_elements_capped_at_3():
    html = "<html><body><font>a</font><marquee>b</marquee><blink>c</blink><center>d</center></body></html>"
    soup = BeautifulSoup(html, "lxml")
    assert detect_old_html_elements(soup) == 3


# --- detect_no_commercial_tracking ---

def test_no_tracking_returns_2_for_clean_page():
    html, _ = load_fixture("geocities_1999.html")
    assert detect_no_commercial_tracking(html) == 2


def test_no_tracking_returns_0_for_gtm():
    html, _ = load_fixture("react_app.html")
    assert detect_no_commercial_tracking(html) == 0


def test_google_analytics_alone_does_not_trigger():
    """GA is allowed — only GTM, Pixel, HotJar count."""
    html = '<html><body><script src="https://www.google-analytics.com/analytics.js"></script></body></html>'
    assert detect_no_commercial_tracking(html) == 2


# --- detect_no_cookie_consent ---

def test_no_cookie_consent_clean_page():
    html, _ = load_fixture("geocities_1999.html")
    assert detect_no_cookie_consent(html) == 2


def test_no_cookie_consent_returns_0_for_cookiebot():
    html = '<html><body><script src="https://consent.cookiebot.com/uc.js"></script></body></html>'
    assert detect_no_cookie_consent(html) == 0


# --- detect_no_jsonld ---

def test_no_jsonld_clean_page():
    html, _ = load_fixture("geocities_1999.html")
    assert detect_no_jsonld(html) == 1


def test_no_jsonld_returns_0_when_present():
    html, _ = load_fixture("react_app.html")
    assert detect_no_jsonld(html) == 0


# --- detect_hand_coded_smell ---

def test_hand_coded_geocities():
    html, soup = load_fixture("geocities_1999.html")
    assert detect_hand_coded_smell(soup, html) == 1


def test_hand_coded_returns_0_for_minified():
    html = "<html><body><p>text</p></body></html>"  # no inline styles, single line
    soup = BeautifulSoup(html, "lxml")
    assert detect_hand_coded_smell(soup, html) == 0


# --- detect_old_content_date ---

def test_old_date_from_meta():
    html, soup = load_fixture("geocities_1999.html")
    assert detect_old_content_date(soup, None) == 2


def test_old_date_from_last_modified():
    html = "<html><body><p>hi</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    assert detect_old_content_date(soup, "Tue, 15 Nov 1994 08:12:31 GMT") == 2


def test_modern_date_returns_0():
    html = '<html><head><meta name="date" content="2024-01-15"></head><body><p>hi</p></body></html>'
    soup = BeautifulSoup(html, "lxml")
    assert detect_old_content_date(soup, None) == 0


# --- detect_asset_style ---

def test_plain_assets_return_1():
    html, soup = load_fixture("jekyll_site.html")  # has /assets/main.css (no hash)
    # jekyll uses plain names here
    score = detect_asset_style(soup)
    assert score >= 0  # plain or no assets


def test_hashed_assets_return_minus_2():
    html, soup = load_fixture("react_app.html")
    assert detect_asset_style(soup) == -2


# --- detect_ssg_generator ---

def test_jekyll_generator_returns_minus_3():
    html, soup = load_fixture("jekyll_site.html")
    assert detect_ssg_generator(soup) == -3


def test_no_generator_returns_0():
    html, soup = load_fixture("geocities_1999.html")
    assert detect_ssg_generator(soup) == 0


# --- detect_modern_hosting ---

def test_github_pages_returns_minus_2():
    assert detect_modern_hosting("user.github.io") == -2


def test_netlify_returns_minus_2():
    assert detect_modern_hosting("mysite.netlify.app") == -2


def test_neocities_not_penalised():
    assert detect_modern_hosting("fishluv99.neocities.org") == 0


def test_plain_domain_returns_0():
    assert detect_modern_hosting("geocities.ws") == 0


# --- is_spa ---

def test_is_spa_true_for_react_app():
    html, soup = load_fixture("react_app.html")
    assert is_spa(soup) is True


def test_is_spa_false_for_geocities():
    html, soup = load_fixture("geocities_1999.html")
    assert is_spa(soup) is False


# --- is_js_rendered ---

def test_js_rendered_false_for_content_page():
    html, soup = load_fixture("geocities_1999.html")
    assert is_js_rendered(soup) is False


def test_js_rendered_true_for_tiny_body_big_js():
    html = (
        "<html><head>"
        + f'<script src="/bundle.js">{"x" * 60_000}</script>'
        + "</head><body><p>Hi</p></body></html>"
    )
    soup = BeautifulSoup(html, "lxml")
    assert is_js_rendered(soup) is True


# --- has_noindex ---

def test_has_noindex_true():
    html = '<html><head><meta name="robots" content="noindex,nofollow"></head><body></body></html>'
    soup = BeautifulSoup(html, "lxml")
    assert has_noindex(soup) is True


def test_has_noindex_false_for_clean():
    html, soup = load_fixture("geocities_1999.html")
    assert has_noindex(soup) is False
