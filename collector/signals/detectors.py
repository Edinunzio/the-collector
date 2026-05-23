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
    has_local = False
    for tag in soup.find_all(["link", "script"]):
        src = tag.get("href") or tag.get("src") or ""
        if not src:
            continue
        # Skip external/absolute URLs
        if src.startswith(("http://", "https://", "//")):
            continue
        # Only count CSS/JS assets
        if not (src.endswith(".css") or src.endswith(".js") or ".css?" in src or ".js?" in src):
            continue
        has_local = True
        if _HASHED_ASSET.search(src):
            return -2
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
