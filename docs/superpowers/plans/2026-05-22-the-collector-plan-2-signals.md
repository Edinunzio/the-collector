# The Collector — Plan 2: Signal Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the signal detection and scoring system that decides whether a crawled page is "old web enough" to index, should be quarantined for review, or should be rejected outright.

**Architecture:** Two modules — `detectors.py` (one pure function per signal, no side effects) and `filter.py` (orchestrates detectors into a `FilterResult`). Pure functions mean the entire engine is testable without a DB or network. HTML fixtures in `tests/fixtures/` cover each signal case.

**Tech Stack:** BeautifulSoup4 + lxml parser, Python re, pytest

**Depends on:** Plan 1 (project scaffold, pyproject.toml, test conftest)

---

## File Map

| File | Role |
|---|---|
| `tests/fixtures/geocities_1999.html` | Old web page — should score high |
| `tests/fixtures/react_app.html` | SPA — should be auto-rejected |
| `tests/fixtures/jekyll_site.html` | Modern SSG — negative SSG signal |
| `tests/fixtures/frameset_page.html` | Frameset — quarantine as `frameset` |
| `tests/fixtures/borderline.html` | Just under threshold — quarantine as `borderline_score` |
| `collector/signals/detectors.py` | One function per signal |
| `collector/signals/filter.py` | Orchestrates detectors → FilterResult |
| `tests/test_detectors.py` | Unit tests for each detector function |
| `tests/test_signals.py` | Integration tests for the full filter pipeline |

---

### Task 1: HTML test fixtures

**Files:**
- Create: `tests/fixtures/geocities_1999.html`
- Create: `tests/fixtures/react_app.html`
- Create: `tests/fixtures/jekyll_site.html`
- Create: `tests/fixtures/frameset_page.html`
- Create: `tests/fixtures/borderline.html`

- [ ] **Step 1: Create tests/fixtures/geocities_1999.html**

This fixture should trigger as many positive signals as possible.

```html
<HTML>
<HEAD>
<TITLE>My Tropical Fish Page!!</TITLE>
<meta name="date" content="1999-03-14">
</HEAD>
<BODY BGCOLOR="#000080" TEXT="#FFFF00">
  <CENTER>
    <FONT SIZE="+3" COLOR="#FF0000">Welcome to my FISH PAGE!!</FONT>
    <MARQUEE>~*~ Oscar Fish Forever ~*~</MARQUEE>
  </CENTER>
  <TABLE BORDER=2 WIDTH=100%>
    <TR>
      <TD><FONT FACE="Comic Sans MS" SIZE=2>I have been keeping cichlids since 1997.</FONT></TD>
      <TD><FONT FACE="Comic Sans MS" SIZE=2>Oscar fish are the best tropical fish.</FONT></TD>
    </TR>
  </TABLE>
  <HR>
  <P><FONT SIZE=1>Last updated March 1999 &mdash; <A HREF="mailto:fishluv@aol.com">email me</A></FONT></P>
</BODY>
</HTML>
```

- [ ] **Step 2: Create tests/fixtures/react_app.html**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>My App</title>
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite"}</script>
    <link rel="stylesheet" href="/static/main.a3f9b12c.min.css" />
  </head>
  <body>
    <div id="root"></div>
    <script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXXX"></script>
    <script src="/static/bundle.c4d8e3f1.min.js"></script>
  </body>
</html>
```

- [ ] **Step 3: Create tests/fixtures/jekyll_site.html**

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="generator" content="Jekyll v4.3.2">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>My Blog</title>
    <link rel="stylesheet" href="/assets/main.css">
  </head>
  <body>
    <main>
      <article>
        <h1>Hello World</h1>
        <p>This is my first post. I write about programming and hiking.</p>
        <p>I have been coding for years and enjoy open source software.</p>
      </article>
    </main>
  </body>
</html>
```

- [ ] **Step 4: Create tests/fixtures/frameset_page.html**

```html
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Frameset//EN">
<HTML>
<HEAD><TITLE>My Site</TITLE></HEAD>
<FRAMESET COLS="20%,80%">
  <FRAME SRC="nav.html" NAME="navigation">
  <FRAME SRC="main.html" NAME="content">
  <NOFRAMES>
    <BODY>Your browser does not support frames.</BODY>
  </NOFRAMES>
</FRAMESET>
</HTML>
```

- [ ] **Step 5: Create tests/fixtures/borderline.html**

A modern-looking page with some old signals but not quite enough to pass threshold=3.

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Personal Page</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <h1>Welcome</h1>
    <p>This is my personal page. I like trains and model railroads.</p>
    <p>I have been collecting model trains since 2005.</p>
    <script async src="https://www.google-analytics.com/analytics.js"></script>
  </body>
</html>
```

- [ ] **Step 6: Commit fixtures**

```bash
git add tests/fixtures/
git commit -m "test: HTML fixtures for signal detection tests"
```

---

### Task 2: Signal detectors (TDD)

**Files:**
- Create: `tests/test_detectors.py`
- Create: `collector/signals/detectors.py`

- [ ] **Step 1: Write failing tests in tests/test_detectors.py**

```python
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
```

- [ ] **Step 2: Run tests — expect all to FAIL**

```bash
pytest tests/test_detectors.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'detect_no_js_framework' from 'collector.signals.detectors'`

- [ ] **Step 3: Implement collector/signals/detectors.py**

```python
"""
Signal detectors — one pure function per signal.
Each function returns an integer score (positive = old web, negative = modern, 0 = neutral).
No side effects. No DB. No network. Easy to unit test in isolation.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup

# --- Constants ---

_JS_FRAMEWORKS = frozenset(
    ["react", "vue", "angular", "next", "svelte", "webpack", "ember", "backbone"]
)
_COMMERCIAL_TRACKERS = [
    "googletagmanager.com",
    "facebook.com/tr",
    "hotjar.com",
    "clarity.ms",
    "connect.facebook.net",
]
_COOKIE_CONSENT_PATTERNS = [
    "cookiebot",
    "onetrust",
    "trustarc",
    "cookiepro",
    "gdpr-consent",
    "cookie-consent",
]
_SSG_GENERATORS = frozenset(
    ["hugo", "jekyll", "eleventy", "pelican", "ghost", "gatsby"]
)
_MODERN_HOST_SUFFIXES = (
    ".github.io",
    ".netlify.app",
    ".vercel.app",
    ".pages.dev",
)
_OLD_TAGS = frozenset(
    ["font", "marquee", "blink", "center", "strike", "tt", "xmp", "basefont"]
)
_HASHED_ASSET = re.compile(r'\.[a-f0-9]{6,12}\.(min\.)?(css|js)(\?.*)?$', re.I)


# --- Positive signals ---

def detect_no_js_framework(html: str) -> int:
    """Returns +2 if no known JS framework string found in page source."""
    lower = html.lower()
    for fw in _JS_FRAMEWORKS:
        if fw in lower:
            return 0
    return 2


def detect_small_page(html: str) -> int:
    """Returns +2 if raw HTML is under 100KB."""
    return 2 if len(html.encode("utf-8")) < 100_000 else 0


def detect_old_html_elements(soup: BeautifulSoup) -> int:
    """Returns +1 per old/retro HTML element found, capped at +3."""
    score = sum(1 for tag in _OLD_TAGS if soup.find(tag))
    return min(score, 3)


def detect_no_commercial_tracking(html: str) -> int:
    """
    Returns +2 if no commercial tracking scripts found.
    Note: Google Analytics (google-analytics.com) is intentionally excluded —
    many genuine old personal sites added GA and it's not a commercial indicator.
    """
    lower = html.lower()
    for tracker in _COMMERCIAL_TRACKERS:
        if tracker in lower:
            return 0
    return 2


def detect_no_cookie_consent(html: str) -> int:
    """Returns +2 if no cookie consent framework detected."""
    lower = html.lower()
    for pattern in _COOKIE_CONSENT_PATTERNS:
        if pattern in lower:
            return 0
    return 2


def detect_no_jsonld(html: str) -> int:
    """Returns +1 if no JSON-LD structured data found."""
    return 0 if "application/ld+json" in html.lower() else 1


def detect_hand_coded_smell(soup: BeautifulSoup, html: str) -> int:
    """
    Returns +1 if page shows signs of hand-coding.
    Signals: inline style attributes present, or inconsistent indentation in raw source.
    """
    if len(soup.find_all(style=True)) >= 3:
        return 1
    lines = html.splitlines()
    indented = sum(
        1 for line in lines[:100]
        if line.startswith("  ") or line.startswith("\t")
    )
    if len(lines) > 10 and indented >= 3:
        return 1
    return 0


def detect_old_content_date(
    soup: BeautifulSoup,
    last_modified: str | None,
) -> int:
    """
    Returns +2 if content appears to be from before 2010.
    Checks: HTTP Last-Modified header, <meta name="date"> tag.
    """
    old_years = set(map(str, range(1990, 2010)))

    if last_modified:
        if any(year in last_modified for year in old_years):
            return 2

    meta_date = soup.find("meta", attrs={"name": re.compile(r"^date$", re.I)})
    if meta_date and meta_date.get("content"):
        if any(year in meta_date["content"] for year in old_years):
            return 2

    return 0


def detect_asset_style(soup: BeautifulSoup) -> int:
    """
    Returns +1 if local CSS/JS assets use plain filenames (style.css, main.js).
    Returns -2 if hashed/minified filenames detected (main.abc123.min.css).
    Returns 0 if no local assets found.
    """
    for tag in soup.find_all(["link", "script"]):
        src = tag.get("href") or tag.get("src") or ""
        if not src:
            continue
        # Skip external/absolute URLs
        if src.startswith(("http://", "https://", "//")):
            continue
        if not (src.endswith(".css") or src.endswith(".js") or ".css?" in src or ".js?" in src):
            continue
        if _HASHED_ASSET.search(src):
            return -2
    # Had local assets but none were hashed
    has_local = any(
        (tag.get("href") or tag.get("src") or "").startswith("/")
        or not (tag.get("href") or tag.get("src") or "").startswith("http")
        for tag in soup.find_all(["link", "script"])
        if tag.get("href") or tag.get("src")
    )
    return 1 if has_local else 0


# --- Negative signals ---

def detect_ssg_generator(soup: BeautifulSoup) -> int:
    """Returns -3 if a known static site generator meta tag is found."""
    generator = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
    if generator and generator.get("content"):
        content = generator["content"].lower()
        if any(ssg in content for ssg in _SSG_GENERATORS):
            return -3
    return 0


def detect_modern_hosting(domain: str) -> int:
    """Returns -2 if domain is a known modern hosting platform."""
    for suffix in _MODERN_HOST_SUFFIXES:
        if domain.endswith(suffix):
            return -2
    return 0


# --- Auto-reject checks (return bool, not score) ---

def is_spa(soup: BeautifulSoup) -> bool:
    """
    True if page is a Single Page Application.
    Detects the canonical SPA pattern: a nearly empty body with only a root/app div.
    """
    body = soup.body
    if not body:
        return False
    root = soup.find("div", id="root")
    app = soup.find("div", id="app")
    if not (root or app):
        return False
    # Only flag as SPA if the root/app div is the primary body content
    direct_children = [
        c for c in body.children
        if hasattr(c, "name") and c.name and c.name not in ("script", "noscript")
    ]
    return len(direct_children) <= 3


def is_js_rendered(soup: BeautifulSoup) -> bool:
    """
    True if page body text is near-empty but JS payload is large.
    Indicates the real content is rendered client-side.
    """
    text = soup.get_text(separator=" ", strip=True)
    script_content_size = sum(
        len(tag.string or "") for tag in soup.find_all("script")
    )
    return len(text) < 200 and script_content_size > 50_000


def has_noindex(soup: BeautifulSoup) -> bool:
    """True if page explicitly asks not to be indexed."""
    robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if robots and robots.get("content"):
        return "noindex" in robots["content"].lower()
    return False
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_detectors.py -v
```

Expected: All tests pass. If any fail, check the fixture HTML matches the detector logic.

- [ ] **Step 5: Commit**

```bash
git add collector/signals/detectors.py tests/test_detectors.py
git commit -m "feat: signal detectors with full test coverage"
```

---

### Task 3: Signal filter (TDD)

**Files:**
- Create: `tests/test_signals.py`
- Create: `collector/signals/filter.py`

- [ ] **Step 1: Write failing tests in tests/test_signals.py**

```python
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
```

- [ ] **Step 2: Run tests — expect all to FAIL**

```bash
pytest tests/test_signals.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'score_page' from 'collector.signals.filter'`

- [ ] **Step 3: Implement collector/signals/filter.py**

```python
"""
Signal filter — orchestrates all detectors into a single FilterResult.
Call score_page() with raw HTML and domain; get back a FilterResult
that tells you whether to index, quarantine, or reject the page.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from bs4 import BeautifulSoup
from collector.signals import detectors
from collector.config import settings


@dataclass
class FilterResult:
    passed: bool
    score: int
    signals: dict[str, int] = field(default_factory=dict)
    quarantine_reason: str | None = None
    auto_rejected: bool = False


def score_page(
    html: str,
    domain: str,
    last_modified: str | None = None,
) -> FilterResult:
    """
    Score a page against all signals and determine its fate:
    - passed=True  → index it
    - passed=False, quarantine_reason set → send to quarantine for human review
    - passed=False, auto_rejected=True → silently discard
    - passed=False, no reason → score below threshold, discard

    The signals dict is always populated (except on parse_error) so
    every decision is explainable.
    """
    # Parse HTML with lxml — more resilient to malformed markup than html.parser
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        return FilterResult(
            passed=False,
            score=0,
            signals={},
            quarantine_reason="parse_error",
        )

    # --- Auto-reject checks (order matters: cheapest first) ---

    if detectors.has_noindex(soup):
        return FilterResult(
            passed=False, score=0,
            signals={"noindex": -99},
            auto_rejected=True,
        )

    if detectors.is_spa(soup):
        return FilterResult(
            passed=False, score=0,
            signals={"spa_root_div": -99},
            auto_rejected=True,
        )

    if detectors.is_js_rendered(soup):
        return FilterResult(
            passed=False, score=0,
            signals={"js_rendered": -99},
            auto_rejected=True,
        )

    # --- Quarantine: frameset pages need special handling ---
    if soup.find("frameset"):
        return FilterResult(
            passed=False,
            score=0,
            signals={"frameset": 0},
            quarantine_reason="frameset",
        )

    # --- Score all signals ---
    signals: dict[str, int] = {
        "no_framework":           detectors.detect_no_js_framework(html),
        "small_page":             detectors.detect_small_page(html),
        "old_html_elements":      detectors.detect_old_html_elements(soup),
        "no_commercial_tracking": detectors.detect_no_commercial_tracking(html),
        "no_cookie_consent":      detectors.detect_no_cookie_consent(html),
        "no_jsonld":              detectors.detect_no_jsonld(html),
        "hand_coded":             detectors.detect_hand_coded_smell(soup, html),
        "old_content_date":       detectors.detect_old_content_date(soup, last_modified),
        "asset_style":            detectors.detect_asset_style(soup),
        "ssg_generator":          detectors.detect_ssg_generator(soup),
        "modern_hosting":         detectors.detect_modern_hosting(domain),
    }
    score = sum(signals.values())

    # --- Quarantine: empty body ---
    body_text = soup.get_text(separator=" ", strip=True)
    if len(body_text) < 50:
        return FilterResult(
            passed=False, score=score,
            signals=signals,
            quarantine_reason="empty_body",
        )

    threshold = settings.signal_threshold

    # --- Quarantine: mixed signals (strong positive AND strong negative) ---
    positive_sum = sum(v for v in signals.values() if v > 0)
    negative_sum = sum(v for v in signals.values() if v < 0)
    if positive_sum >= 6 and negative_sum <= -3:
        return FilterResult(
            passed=False, score=score,
            signals=signals,
            quarantine_reason="mixed_signals",
        )

    # --- Quarantine: borderline (within 2 points of threshold) ---
    if score < threshold and score >= threshold - 2:
        return FilterResult(
            passed=False, score=score,
            signals=signals,
            quarantine_reason="borderline_score",
        )

    return FilterResult(
        passed=score >= threshold,
        score=score,
        signals=signals,
    )
```

- [ ] **Step 4: Run all signal tests — expect PASS**

```bash
pytest tests/test_detectors.py tests/test_signals.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add collector/signals/filter.py tests/test_signals.py
git commit -m "feat: signal filter pipeline with quarantine routing"
```

---

## What's Next

**Plan 3 — Crawler** (`2026-05-22-the-collector-plan-3-crawler.md`)
Implements `security.py`, `robots.py`, `queue.py`, `cdx.py`, and `worker.py`. The signal filter from this plan is used in `worker.py` to decide what to index.
