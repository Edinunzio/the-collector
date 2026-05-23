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
    except Exception:
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
