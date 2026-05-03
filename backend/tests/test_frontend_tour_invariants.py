"""Pytest gating for the W5-FRONTEND tour-step copy invariants.

The dashboard onboarding tour step 2 (`frontend/app/page.tsx` →
`TOUR_STEPS[1]`) was reframed by W5-FRONTEND (commit 311339e on the
upstream agent branch, cherry-picked here as 6496ef8) to remove three
overclaim risks:

  1. The rejected `'Live data'` title (overconfident framing the W1/W2
     unsafe-wording passes already downgraded on the `/investment` LIVE
     chip and the global Sidebar `Live Data` chip).
  2. The rejected blanket `'All numbers are backed by real Romanian
     market data, refreshed daily.'` description (false on the same
     page because the two summary cards above the badge are tagged
     ILLUSTRATIVE with hardcoded figures).
  3. The rejected `refreshed daily` cadence claim (the badge actually
     surfaces the manifest's delivery-date range and lights up an amber
     `stale` chip when lag exceeds 60 days — there is no daily-refresh
     promise).

The runbook section that documents these invariants
(SOURCE_CONFIDENCE_AUDIT.md §11.2) is still on a deferred agent branch.
This test codifies the same invariants as a real pytest assertion so a
future copy regression is caught at test time, not by human grep
review. This is the "convention + greps → enforced check" upgrade
called out in the morning review.

Each invariant maps to one assertion below; the test fails with a
specific message naming which §11.x rule was violated, so a future
reviewer can jump straight to the runbook.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGE_TSX = ROOT / "frontend" / "app" / "page.tsx"
BADGE_TSX = ROOT / "frontend" / "components" / "ui" / "DataFreshnessBadge.tsx"


def _strip_line_comments(src: str) -> str:
    """Remove `// …` line comments so wording-audit comments that quote
    the rejected literals don't fire negative-check assertions.

    Block comments (`/* … */`) are not used in `frontend/app/page.tsx`
    today, so a simple line-comment strip is enough. Strings on the
    same line as `//` are not stripped — TS string syntax in this file
    does not contain `//`."""
    return re.sub(r"(?m)^\s*//.*$", "", src)


@pytest.fixture(scope="module")
def page_src() -> str:
    assert PAGE_TSX.is_file(), f"{PAGE_TSX} missing"
    return PAGE_TSX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page_active(page_src: str) -> str:
    """`page.tsx` with `// …` comments stripped — used for negative checks
    so the inline W5-FRONTEND audit comment that quotes the rejected
    literals does not trip the test."""
    return _strip_line_comments(page_src)


@pytest.fixture(scope="module")
def badge_src() -> str:
    assert BADGE_TSX.is_file(), f"{BADGE_TSX} missing"
    return BADGE_TSX.read_text(encoding="utf-8")


# §11.1.1 (positive) — approved title MUST be present.
def test_tour_step2_title_is_market_data_backing(page_active: str) -> None:
    assert "title: 'Market data backing'" in page_active, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.1: tour step 2 title must read "
        "'Market data backing' (matching the DataFreshnessBadge heading)."
    )


# §11.1.1 (negative) — rejected `'Live data'` title MUST NOT come back as
# active code.
def test_tour_step2_does_not_reintroduce_live_data_title(page_active: str) -> None:
    assert "title: 'Live data'" not in page_active, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.1: tour step 2 title `'Live data'` "
        "was downgraded by W5-FRONTEND — same family as the W1/W2 LIVE "
        "chip downgrades on /investment (3275e29) and the Sidebar "
        "(5a913e1). Do not reintroduce it."
    )


# §11.1.2 (negative) — rejected blanket "all numbers" description MUST
# NOT come back as active code.
def test_tour_step2_does_not_reintroduce_blanket_all_numbers_claim(
    page_active: str,
) -> None:
    assert "All numbers are backed by real Romanian market data" not in page_active, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.2: blanket claim `'All numbers are "
        "backed by real Romanian market data…'` was downgraded by "
        "W5-FRONTEND — false on the dashboard because the two summary "
        "cards above the badge are tagged ILLUSTRATIVE."
    )


# §11.1.3 (negative) — rejected `refreshed daily` cadence claim MUST NOT
# come back as active code.
def test_tour_step2_does_not_claim_refreshed_daily(page_active: str) -> None:
    assert not re.search(r"refreshed daily", page_active, re.IGNORECASE), (
        "SOURCE_CONFIDENCE_AUDIT §11.1.3: `refreshed daily` cadence claim "
        "was downgraded by W5-FRONTEND — DataFreshnessBadge surfaces the "
        "manifest delivery-date range and an amber `stale` chip at >60 "
        "days lag, not a daily-refresh promise."
    )


# §11.1.4 (positive, two handles) — manifest endpoint and ILLUSTRATIVE
# qualifier MUST appear in the description so a hurried reader cannot
# read the step as a blanket guarantee.
def test_tour_step2_description_names_manifest_and_illustrative(
    page_active: str,
) -> None:
    assert "/api/v1/data/manifest" in page_active, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.4: tour step 2 description must "
        "name the manifest endpoint `/api/v1/data/manifest` so the claim "
        "is scoped to what the badge actually reads."
    )
    assert "ILLUSTRATIVE" in page_active, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.5: tour step 2 description must "
        "name `ILLUSTRATIVE` so a reader who skims the summary cards "
        "above the badge cannot read €4.3M / €1.8M as live data."
    )


# §11.1.6 (DOM target) — `data-tour="step-2"` MUST still wrap a
# DataFreshnessBadge element. The grep below is approximated by reading
# the file for the wrapper and checking the next non-blank lines name
# DataFreshnessBadge.
def test_tour_step2_target_wraps_data_freshness_badge(page_src: str) -> None:
    # Match the JSX wrapper specifically — a `<…  data-tour="step-2"…>`
    # opening tag — and ignore both the `target: '[data-tour="step-2"]'`
    # selector string in `TOUR_STEPS` and any `//` comments. Captures
    # the line index so we can inspect the following lines.
    lines = page_src.splitlines()
    wrapper_pattern = re.compile(r'<[A-Za-z][^>]*\bdata-tour="step-2"')
    wrapper_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if wrapper_pattern.search(ln) and "//" not in ln
        ),
        None,
    )
    assert wrapper_idx is not None, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.6: `<… data-tour=\"step-2\"…>` "
        "JSX wrapper missing — tour copy points at a DOM node that no "
        "longer exists."
    )
    # Inspect the next 5 non-blank source lines for `<DataFreshnessBadge`.
    follow = "\n".join(lines[wrapper_idx + 1 : wrapper_idx + 6])
    assert "<DataFreshnessBadge" in follow, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.6: `data-tour=\"step-2\"` wrapper "
        "no longer wraps `<DataFreshnessBadge>`. The tour copy claims the "
        "badge reads /api/v1/data/manifest; if the wrapper moves to one "
        "of the ILLUSTRATIVE summary cards the copy becomes a DOM-level "
        "lie."
    )


# §11.1.1 (cross-surface) — badge heading MUST still match the tour
# title so the two surfaces do not drift on what the surface is called.
def test_data_freshness_badge_heading_matches_tour_title(badge_src: str) -> None:
    assert "Market Data Backing" in badge_src, (
        "SOURCE_CONFIDENCE_AUDIT §11.1.1 (cross-surface): "
        "DataFreshnessBadge heading `Market Data Backing` is missing — "
        "the badge and the tour copy must agree on what the surface is "
        "called."
    )
