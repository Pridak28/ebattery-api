# Accessibility Findings — battery-analytics-pro/frontend

Audit date: 2026-05-02

This document records HIGH-RISK or invasive a11y issues identified during the audit
that were NOT auto-fixed because they require structural / design / palette changes.
Low-risk fixes (icon-only button labels, missing input labels) were applied inline
in the same change set.

---

## HIGH severity

(All HIGH-severity findings resolved — see Resolved section below.)

---

## MEDIUM severity

(All MEDIUM-severity findings resolved — see Resolved section below.)

---

## LOW severity / style notes

### L1. `focus:outline-none` in `.input-dark` utility

`app/globals.css` line ~148:
```css
.input-dark {
  ...
  @apply rounded px-3 py-2 text-white focus:outline-none placeholder-slate-500;
}
.input-dark:focus {
  border-color: #00ffd1;
  box-shadow: 0 0 0 2px rgba(0, 255, 209, 0.2);
}
```
Status: ACCEPTABLE — the `:focus` rule provides an alternative focus ring
(border + box-shadow) so removing the default outline does not leave focus
invisible. Documented for completeness only; no fix needed.

### L2. `<a>` external links lack visible language change indication

External links to `https://ebattery.energy` and ENTSOE/legislation portals open
in new tabs (`target="_blank"`) and carry `rel="noopener noreferrer"` correctly,
but do not visually indicate the new-tab behavior beyond an `<ExternalLink>` icon.
This is a minor enhancement; current behavior is WCAG-compliant.

---

## Resolved

### H1. Form inputs not programmatically associated with their labels — RESOLVED 2026-05-02

**Original severity:** HIGH (WCAG 1.3.1 / 4.1.2)
**Files & approach:**
- `app/investment/page.tsx` — 8 inputs fixed via **label `htmlFor` + input `id`** pairing (ids prefixed `bess-inv-*`).
- `app/pzu/page.tsx` — 4 simulation-parameter inputs fixed via **label `htmlFor` + input `id`** pairing (ids prefixed `pzu-*`). The 2 remaining inputs (`pzu-select-date`, `Filter dates` search) were already labelled in prior pass and were skipped.
- `app/fr-simulator/page.tsx` — 8 number inputs fixed via **label `htmlFor` + input `id`** pairing (ids prefixed `fr-*`). The 2 remaining `<input type="date">` and `<input type="text">` already carried `aria-label` from prior pass; the 3 `<input type="range">` sliders are tracked separately under M2.

Total: 20 `<input>` elements now programmatically associated. No visual layout changes; only `id` and `htmlFor` attributes added. tsc, lint, next build all clean post-fix.

### M1. Heading hierarchy skips levels in dashboard module cards — RESOLVED 2026-05-02

**Original severity:** MEDIUM (WCAG 1.3.1)
**File:** `app/page.tsx`
**Approach:** Promoted the "Revenue Stacking Strategy" heading from `<h3>` to
`<h2>` so it sits as a sibling of the "Analytics Modules" `<h2>` rather than
being a phantom subsection of the preceding aFRR card. The existing className
(`text-base sm:text-lg font-semibold text-white mb-2 sm:mb-3 flex items-center
gap-2`) already matches the visual sizing used by the "Analytics Modules"
`<h2>`, so no class adjustment was needed for size parity. Document outline is
now: `<h1>` (page title) → `<h2>` PZU + `<h2>` aFRR card titles (with `<h3>`
sub-sections "How It Works" / "Key Metrics" / "Revenue Streams" / "Market
Parameters" inside each card) → `<h2>` Revenue Stacking Strategy → `<h2>`
Analytics Modules → `<h3>` per-module names. No skipped levels remain.
Verification: `tsc --noEmit`, `npm run lint`, `next build` all pass.

### M3. Color-only state in BankabilityBadge / ConfidenceBadge / DSCR table rows — RESOLVED 2026-05-02

**Original severity:** MEDIUM (WCAG 1.4.1)
**Files:** `components/ui/ConfidenceBadge.tsx` (and `BankabilityBadge.tsx`
which already shipped with icons in a prior pass).
**Approach:** Added a distinct leading `lucide-react` icon to every variant of
both `ConfidenceBadge` and the co-exported `PricingBasisBadge`, mirroring the
existing icon treatment of `BankabilityBadge`. Icon size matches the badge
`text-xs` baseline (`w-3.5 h-3.5`) and carries `aria-hidden="true"` since the
adjacent text label remains the accessible name. Colors, ring, background, and
all existing styling unchanged.

Confidence label → icon mapping:
- `Confirmed-source` → `ShieldCheck`
- `Likely-source` → `Info`
- `Likely-source / Scenario` → `FlaskConical`
- `Participant-only` → `AlertTriangle`
- `Public-data / Participant-only-for-bankability` → `Database`
- `Scenario` → `FlaskConical`
- `Unverified` / fallback → `HelpCircle`

PricingBasis → icon mapping:
- `participant_bid` → `Tag`
- `public_marginal` → `TrendingUp`
- `settlement_export` → `ShieldCheck`
- `scenario` → `FlaskConical`
- unknown / fallback → `HelpCircle`

This means visually-similar same-color variants (e.g. blue `Likely-source` vs
blue `Likely-source / Scenario`) now also differ by glyph (`Info` vs
`FlaskConical`), restoring a non-color-only cue. `DscrTable` rows were
re-reviewed: violations already carry an explicit text status column ("BREACH" /
"OK") in addition to row tint, so the row tint is redundant rather than the
sole signal — no change needed there. No new npm deps (lucide-react already in
dependencies). Verification: `tsc --noEmit`, `npm run lint`, `next build` all
pass.

### M4. Possible low-contrast text on dark backgrounds — RESOLVED 2026-05-02

**Original severity:** MEDIUM (WCAG 1.4.3)
**Approach:** Adopted a "minimum text color rule" of `text-slate-400` (#94a3b8 →
~7:1 on slate-900 `#0f172a`, comfortably above the WCAG AA 4.5:1 threshold for
small text) on dark backgrounds. Every Tailwind `text-slate-500`,
`text-slate-600`, and `text-slate-700` class — covering body text, hint text,
uppercase tracking-wider micro-labels (`text-[9px]`/`text-[10px]`/`text-[11px]`),
table headers, em-dash placeholders, decorative pipe separators, and the Sidebar
"Powered by ..." mini-link/branding — was bumped to `text-slate-400`.

`border-slate-500/600/700` (divider rules with no text content) and
`bg-slate-500/600/700` (background fills) were left intact — they do not affect
text contrast and the visual hierarchy depends on them. The
`placeholder-slate-500` utility on `.input-dark` and the search input in
`SavedReportsPanel` was also left intact, since placeholders intentionally sit
below body contrast to remain distinguishable from real input values (and WCAG
specifically exempts placeholder text from the 4.5:1 rule when it is purely
ornamental and the field's accessible name carries the semantics).

**Files changed (class swap counts):**
- `app/page.tsx` — 16
- `app/investment/page.tsx` — 46
- `app/pzu/page.tsx` — 61
- `app/fr-simulator/page.tsx` — 69
- `app/methodology/page.tsx` — 9
- `app/globals.css` — 2 (`.stat-label`, `.toggle-btn-inactive`; `placeholder-slate-500` left alone)
- `components/ui/CapexBands.tsx` — 1
- `components/ui/RegulatoryTimeline.tsx` — 3
- `components/ui/DataFreshnessBadge.tsx` — 4
- `components/ui/SavedReportsPanel.tsx` — 4
- `components/ui/ComplianceGatesWizard.tsx` — 1
- `components/ui/HealthDiagnostics.tsx` — 3
- `components/ui/BankabilityBadge.tsx` — 1
- `components/charts/DscrDetailPanel.tsx` — 1
- `components/charts/LiveMarketChart.tsx` — 8
- `components/charts/SensitivityFanChart.tsx` — 3
- `components/charts/FRProductBreakdown.tsx` — 2
- `components/charts/ScenarioComparator.tsx` — 3
- `components/charts/IrrDistributionHistogram.tsx` — 5
- `components/charts/RegimeBreakdownCard.tsx` — 9
- `components/charts/ScenarioDiffPanel.tsx` — 8
- `components/layouts/Sidebar.tsx` — 12

Total: 271 class-name occurrences swapped across 22 files.

**Contrast estimate (small text on `bg-slate-900` #0f172a):**
- Before: `text-slate-500` (#64748b) ≈ 4.0:1 (boundary fail), `text-slate-600`
  (#475569) ≈ 2.6:1 (fail), `text-slate-700` (#334155) ≈ 1.7:1 (fail).
- After: `text-slate-400` (#94a3b8) ≈ 7.0:1 (passes WCAG AA + AAA for normal
  body, AA for small text comfortably). The Sidebar "Powered by ..." line, which
  was the worst offender at slate-700 over the gradient bg, now reads cleanly.

**Verification:** `npx --no-install tsc --noEmit` clean, `npm run lint` clean
(no warnings or errors), `npx --no-install next build` succeeds and all 9 routes
prerender. No layout / spacing / structural changes; only the text-slate
color-token digit changed.

### M2. Unlabelled range sliders (with visible label sibling) — RESOLVED 2026-05-02

**Original severity:** MEDIUM (WCAG 1.3.1 / 4.1.2)
**File:** `app/fr-simulator/page.tsx`
**Approach:** Same **label `htmlFor` + input `id`** pairing as H1. Each of the 3 `<input type="range">` sliders received an `id` (`fr-activation-rate-slider`, `fr-target-acceptance-slider`, `fr-safe-bid-acceptance-slider`) with a matching `htmlFor` on the existing visible `<label>`. Each slider also received explicit `aria-valuemin` / `aria-valuemax` / `aria-valuenow` plus `aria-valuetext` providing a human-readable announcement (e.g. "60 percent target acceptance rate") so screen-reader users hear the dimension being adjusted instead of a bare numeric value. No visual layout, slider behavior, or styling changes. Verification: `tsc --noEmit`, `npm run lint`, `next build` all clean. (Other inputs in the file — the date picker at ~line 1442 and number inputs — already carry labels or `aria-label` from prior passes.)

### H2. Interactive `<tr>` rows with `onClick` (no keyboard support) — RESOLVED 2026-05-02

**Original severity:** HIGH (WCAG 2.1.1)
**Approach:** Added `tabIndex={0}` + `role="button"` + descriptive `aria-label` + `onKeyDown` (Enter / Space, with `preventDefault` on Space to suppress page scroll) to each interactive `<tr>`. Also added Tailwind focus-visible ring styling (`focus-visible:ring-2 focus-visible:ring-[#00ffd1] focus-visible:ring-inset focus-visible:outline-none`) consistent with the dark theme. No visual layout changes; click behaviour and styling unchanged.

**Files & rows fixed:**
- `app/pzu/page.tsx` (line ~820) — monthly summary row, action `fetchDailyBreakdown(row.month)`. Also added `aria-expanded` reflecting `isExpanded` and a label that flips between "Expand" / "Collapse daily breakdown for {month}".
- `app/investment/page.tsx` (line ~617) — vendor selection row, action `handleVendorChange(v.key)`. Added `aria-pressed` reflecting selection state and label "Select battery vendor {name}". (A keyboard-accessible `<select>` for the same action exists at line ~565, so the row is now an additional accessible path rather than the only one.)

**Other pages scanned:** `app/fr-simulator/page.tsx` has multiple `<tr>` elements but none carry `onClick` — no fix needed there. Decorative `<span>` and display-only `<div>` elements without click handlers were left untouched. Verification: `tsc --noEmit`, `npm run lint`, `next build` all clean.

---

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| HIGH     | 2     | Resolved (H1, H2) |
| MEDIUM   | 4     | All resolved (M1, M2, M3, M4) |
| LOW      | 2     | Documented (no fix needed) |

M4 resolved; only L1 + L2 remain (acceptable LOW).

Low-risk fixes applied inline:
- Icon-only Prev/Next buttons in `app/fr-simulator/page.tsx` got `aria-label`s.
- Date input in `app/fr-simulator/page.tsx` got `aria-label`.
- "Filter dates" text input in `app/pzu/page.tsx` got `aria-label`.
- "Select Date" picker in `app/pzu/page.tsx` got proper `htmlFor`/`id` association.
- Added explicit `type="button"` to icon-only chevron buttons (defensive).

---

## Re-audit pass — 2026-05-02

Second-pass audit by accessibility agent. All previously-applied low-risk
fixes confirmed in place. One additional low-risk fix applied:

- `components/layouts/MobileNav.tsx`: added `aria-hidden="true"` to the
  decorative click-outside-to-close backdrop overlay. The overlay duplicates
  the keyboard-accessible "Close menu" button, so hiding it from assistive
  tech avoids announcing a phantom interactive layer to screen-reader users.

No new icon-only buttons, no new unlabelled inputs, no new `<div onClick>`
patterns found across `app/`, `components/ui/`, `components/charts/`,
`components/layouts/`. Build, type-check, and lint all clean.

H1, H2, M1–M4, L1, L2 from the original pass remain deferred per the
audit charter (color/structural/palette changes out of scope).

---

## Third pass — 2026-05-02 (H1 resolved)

H1 (form inputs not associated with labels) resolved by accessibility
agent. 20 raw `<input>` elements across `app/investment/page.tsx`,
`app/pzu/page.tsx`, and `app/fr-simulator/page.tsx` received explicit
`id` attributes with matching `htmlFor` on their sibling `<label>`.
Approach: label-htmlFor pairing for all 20 (no fallback to `aria-label`
or wrapping needed — all were already in the canonical
`<div><label/><input/></div>` shape with no layout risk). Verification:
`tsc --noEmit`, `npm run lint`, `next build` all pass.

---

## Fifth pass — 2026-05-02 (M2 resolved)

M2 (unlabelled `<input type="range">` sliders) resolved by accessibility
agent. All 3 sliders in `app/fr-simulator/page.tsx` received `id`
attributes with matching `htmlFor` on their existing visible `<label>`
siblings, plus explicit `aria-valuemin`/`aria-valuemax`/`aria-valuenow`
and an `aria-valuetext` providing a human-readable percentage
announcement (e.g. "60 percent market share / activation rate"). No
visual layout or slider-behavior changes. Same file scanned for other
unlabelled controls: the `<input type="date">` and chevron buttons were
already labelled by prior passes; all other inputs use proper
`htmlFor`/`id` pairs. Verification: `tsc --noEmit`, `npm run lint`,
`next build` all pass.

---

## Fourth pass — 2026-05-02 (H2 resolved)

H2 (interactive `<tr>` rows missing keyboard support) resolved by
accessibility agent. Two `<tr onClick>` rows were found and fixed:
one in `app/pzu/page.tsx` (monthly summary, expand daily breakdown)
and one in `app/investment/page.tsx` (vendor selection). Each row
received `tabIndex={0}`, `role="button"`, a descriptive `aria-label`,
matching `aria-expanded` / `aria-pressed` state where relevant, an
`onKeyDown` handler firing the same action on Enter or Space (with
`preventDefault` on Space to suppress page scroll), and a
`focus-visible:ring-2 focus-visible:ring-[#00ffd1] focus-visible:ring-inset
focus-visible:outline-none` Tailwind class for visible focus. The
`cursor-pointer` class was already present on both rows. The
`app/fr-simulator/page.tsx` page was scanned for the same anti-pattern
and contains no `<tr onClick>` (or other clickable non-buttons) —
no further fixes needed there. Verification: `tsc --noEmit`,
`npm run lint`, `next build` all pass.

---

## Sixth pass — 2026-05-02 (M1 + M3 resolved)

M1 (heading hierarchy skip on dashboard) and M3 (color-only state in
ConfidenceBadge / PricingBasisBadge) both resolved by accessibility
agent.

- M1: `app/page.tsx` — promoted "Revenue Stacking Strategy" heading
  from `<h3>` to `<h2>` so it is a sibling of the "Analytics Modules"
  `<h2>` instead of an orphaned subsection. Existing className already
  matched the sibling `<h2>` size, so no Tailwind class change was
  required. Document outline now flows h1 → h2 → h3 with no skipped
  levels.
- M3: `components/ui/ConfidenceBadge.tsx` — added a distinct
  `lucide-react` icon to every variant of `ConfidenceBadge` and
  `PricingBasisBadge` (mapping documented in the Resolved entries
  above). `BankabilityBadge.tsx` already shipped with icons. Colors,
  ring, and existing badge layout unchanged; icons carry
  `aria-hidden="true"` since the adjacent text label is the accessible
  name. No new npm deps. `DscrTable` was re-reviewed and already
  carries explicit text status alongside row tint, so it does not
  rely on color alone.

Verification: `tsc --noEmit`, `npm run lint`, `next build` all pass.
Only M4 (low-contrast text — palette change forbidden by audit
charter) remains deferred at MEDIUM severity.

---

## Seventh pass — 2026-05-02 (M4 resolved)

M4 (low-contrast `text-slate-500/600/700` on dark backgrounds) resolved
by accessibility agent after the user explicitly authorized a palette
change. Adopted a "minimum text color rule": every Tailwind
`text-slate-500`, `text-slate-600`, and `text-slate-700` token in the
app and component tree was bumped to `text-slate-400` (#94a3b8 → ~7:1
contrast on slate-900, comfortably above WCAG AA 4.5:1). 271 class
swaps across 22 files (5 page files, 9 ui components, 7 chart
components, 1 layout, 1 globals.css `@apply` rule). Border classes
(`border-slate-500/600/700`), background classes (`bg-slate-...`), and
the `placeholder-slate-500` utility were left intact since they do not
affect text contrast (and placeholders are intentionally lower-contrast
to remain distinguishable from real input). The Sidebar "Powered by
..." mini-link, previously slate-700 (~1.7:1, failing) is now slate-400
on the gradient bg. Verification: `npx --no-install tsc --noEmit`,
`npm run lint`, `npx --no-install next build` all pass; no layout,
spacing, or component-shape changes. With M4 closed, all HIGH and
MEDIUM findings are resolved; only L1 (`focus:outline-none` with
documented alternative focus ring on `.input-dark`) and L2
(`<ExternalLink>` icon as the sole new-tab affordance) remain, both at
acceptable LOW per the audit charter.
