# Agent prompts: reader experience follow-ups

Ready-to-run briefs for the next passes on the reader (`read_only`) page. Each
one is written so an agent can start cold: what the problem is, where it lives,
the box it must fit in, what "done" looks like, and what not to touch. They are
ordered by how much they need an owner's decision first — the top ones need
none.

Every brief inherits the same constraints. Read them once.

## The box (applies to every prompt)

- Server-rendered Python on the stdlib `http.server`. No framework, no build
  step, no npm. Assets live in `src/kalshi_research_bot/dashboard_assets/`.
- CSP is `script-src 'self'; style-src 'self'; font-src 'self'`. No inline
  `<style>` or `<script>`, no CDN.
- Design tokens are the `:root` block at the top of `app.css`. Reuse them. No
  new colours, no `!important`, no override layer.
- Components already exist: `panel`, `card-head`, `eyebrow`, `section-label`,
  `section-kicker`, `stat-card`/`stat-grid`, `tier-card`/`tier-grid`,
  `slip-card`, `slip-analysis`, `leg-breakdown`, `metric-strip`, `data-row`,
  `badge`, `btn`, `empty-state`, `alert`, `prediction-drawer`,
  `mobile-bottom-nav`. Reuse before inventing.
- Progressive enhancement: the page must read and navigate with JS off.
- WCAG 2.1 AA: 4.5:1 text contrast, visible focus rings, semantic landmarks.
  Muted text is `--text-muted` (`#929bac`); do not darken it.
- 320px to 1440px with zero horizontal overflow.
- Content rules for anything a reader sees or copies: no wagering vocabulary
  (bet, wager, stake, parlay, book, payout, odds boost); no fabricated data
  (no backend, no UI, honest empty state); no implied guarantees (a probability
  is an estimate with its basis visible); no backend nouns (a reader is told
  "Live market data", never "collector feed").
- `tests/test_dashboard_render.py::ReaderResearchFramingTests` already guards
  the reader page's visible text and clipboard payloads for wagering words. If
  you add reader-facing copy, run it. If you add a rendered class, the
  stylesheet test requires it to be styled or used by script.
- Repo rules: feature branch, PR against `Master`, never push to `Master`.
  Preserve every research-only control. Tests: `python -m unittest discover -s
  tests` (33 Postgres-gated failures are expected without a database; do not
  add to them) and `ruff check .`.
- Verify visually: render both roles from `browser_fixtures` (states `live`,
  `empty`, `stale`, `error`, `loading`) and screenshot at 1440 and 390. Check
  `document.documentElement.scrollWidth === innerWidth`.

---

## Prompt 1: Rename "Builder" to "Review" in reader-facing navigation

**Problem.** The reader's top nav says "Builder", the sidebar says "Kalshi
builder" under the label "Builder views", the hero eyebrow says "Live Kalshi
prediction builder", and the tier panel is labelled "Builder status". "Bet
builder" and "parlay builder" are sportsbook product names. The word is not on
the banned list, but it tells a reader this is a place to assemble something to
submit, which is exactly what the product says it is not.

**Where.** `src/kalshi_research_bot/paper_server.py`: the two `Builder` nav
anchors near line 1787–1792 and 1838; `aria-label="Builder views"` and
`Kalshi builder` around 1852–1853; the eyebrow at ~1876; `Builder status` at
~1900. Also `ICON_PATHS["builder"]` (a name, not copy; may stay) and the
`#builder` anchor id, which `app.js` and tests reference.

**Do.**
- Change the visible words. Suggested: nav "Review", sidebar "Kalshi review",
  aria-label "Review views", eyebrow "Live Kalshi market review", section label
  "Review status". Keep the hero `<h1>` unless it also uses the word.
- Keep the element id `#builder` unless you also update every reference in
  `app.js`, the bottom nav, the skip link target, and
  `tests/test_dashboard_render.py::test_javascript_only_targets_ids_that_exist`.
  Renaming the id is optional and a separate commit if you do it.
- Operator page may keep "Builder" in operator-only panels if the operator
  copy uses it; the brief only covers the reader. Simplest is to change both.

**Done when.** No reader-visible text contains "builder" (case-insensitive).
Add `builder` to a small reader-copy denylist test alongside
`ReaderResearchFramingTests` (a new test method, not an edit to the wagering
regex, since "builder" is a product-vocabulary call rather than a hard rule).
Both roles render, tests and ruff clean, screenshots at both widths.

---

## Prompt 2: Replace the hero stat row with one reader-facing summary

**Problem.** The reader's hero shows four `stat-card`s: "Games loaded",
"Combo contracts", "Verified today", "Review tiers ready". Three of them count
what the pipeline did this morning. They are not backend vocabulary, but they
are the strongest reason the reader page still reads as an operator dashboard
with the operator bits removed.

**Where.** `paper_server.py` ~1889–1895 inside `render_dashboard`, the
`stat-grid` with `aria-label="Current builder summary"`. The values come from
`games`, `markets`, `verified_contracts`, `ready_tiers`, `tier_total` already
in scope.

**Do.**
- For the reader, render a single summary sentence or a two-card grid that
  answers "what was checked and when": e.g. one `stat-card` "Contracts
  checked" = `verified_contracts` with `stat-foot` "Confirmed live on Kalshi
  today", plus the existing "Review tiers ready" card. Drop "Games loaded" and
  "Combo contracts" for the reader.
- Gate with the existing `viewer_sees_operations` flag; the operator keeps all
  four.
- Check `.stat-grid` (`app.css` ~581) and make sure two cards do not
  stretch to full width awkwardly at 1440. If they do, add a modifier class (e.g. `stat-grid.is-pair`) with
  existing tokens, not a new component.

**Done when.** Reader page shows two cards, operator page shows four, a test
asserts both, the stylesheet test passes for any new class, screenshots at
1440 and 390.

---

## Prompt 3: Rename the "risk" badge to say what it measures

**Problem.** The `slip-analysis` head shows a badge like `low risk`. The tier
comes from `slip_analysis.risk_tier()` and is computed from leg count,
correlated pairs, and hit probability. "Risk" beside a probability reads as a
recommendation in a research tool; the badge should name the thing it
measures.

**Where.** Badge rendered in `paper_server.py` at ~2249 inside
`render_slip_analysis`, using `_RISK_CLASS` (~2136) and `analysis["risk_tier"]`
(~2171). Tiers are `low`, `moderate`, `high`, `very_high`. The computation in
`slip_analysis.py::risk_tier` (~544) stays as is.

**Do.**
- Map tiers to descriptive labels in `paper_server.py`, e.g. `low` →
  "Few moving parts", `moderate` → "Some fragility", `high` → "Fragile",
  `very_high` → "Very fragile". Or keep a noun and change it: "low variance".
  Pick one and use it for both roles; the operator does not need a different
  word.
- Keep the `risk_tier` key in the analysis JSON; only the rendered label
  changes.
- Add a `title` or a visible `small` explaining the basis ("from leg count,
  correlation, and hit probability") only if it fits the `slip-analysis-head`
  without wrapping at 390. If it does not fit, put it in the existing
  `status-note` under the strip instead.

**Done when.** No rendered badge ends in " risk", a test pins the four labels,
tests/ruff clean, screenshots at both widths.

---

## Prompt 4: One headline probability per slip (needs an owner decision)

**Problem.** For one slip the drawer shows "Implied chance 59.30%" (product of
leg market prices, from `combo_probability_display`) and the card shows
"Estimated to hit 60.1%" (the model's estimate, from `build_slip_analysis`).
Both are legitimate; a non-expert reads them as the tool disagreeing with
itself. PR #102 labelled them and put the estimate first on the card. It did
not decide which number leads in the drawer and the tier tiles.

**Where.** Drawer: `render_compact_slip` ~1502–1523. Tier tiles:
`render_visual_section` ~2395–2412 (`chance_text`, `probability_kind`). Card:
`render_slip_section` and `render_slip_analysis`.

**Ask the owner first.** Two defensible options:
- (a) The model estimate leads everywhere, with the market-implied figure as
  the secondary line ("Market implies 59.3%"). Consistent with the card.
- (b) The market-implied figure leads in the compact views because it needs no
  model and is always available, and the estimate is a card-only detail.

**Do (after the decision).** Make the drawer and tier tiles agree with the
card. Whatever leads, label both with their basis in the same words the card
uses ("Estimated to hit" / "Market implied"). Confidence intervals already
exist for both (`combo_chance_range`, `95% CI`); show them where space allows.

**Done when.** A test asserts the drawer, tile and card lead with the same
kind of probability for the same slip and label it identically.

---

## Prompt 5: Raise the 10px micro-label floor to 11px

**Problem.** Eight selectors set `font-size: 10px` for uppercase labels
(`.metric-strip small`, `.drawer-metrics small`, `.quote-cell small`,
`details.leg-details dt`, `.record-rate small`, `.sports-selection-fair small`,
`.source-data-grid li > span`, `.leg-breakdown thead th`). They pass contrast
but are hard to read on a phone. `section-kicker` is already 11px.

**Where.** `app.css` lines ~716, 860, 964, 993, 1029, 1066, 1169, 1323.

**Do.**
- Change each to 11px. Check the two places most likely to wrap: the
  `metric-strip` cell "Listed combo price" at 390 (the subgrid rule in
  `tests/test_dashboard_render.py` documents the wrap) and the
  `leg-breakdown` table head at 390 (it scrolls horizontally inside
  `.leg-breakdown-scroll`; confirm the scroll container, not the page, takes
  the overflow).
- Do not touch letter-spacing unless a label now overflows its cell; if so,
  reduce to `.05em` before anything else.

**Done when.** `grep -c "font-size: 10px" app.css` is 0, the existing
"micro-type floor" note in `docs/frontend-improvement-research.md` is updated,
and screenshots at 390 show no new wrapping in the strips.

---

## Prompt 6: Drawer as a bottom sheet on mobile (from the earlier plan, P5)

**Problem.** On mobile the `prediction-drawer` is `position: static` and drops
below the main column (`app.css` ~1221). The current slip is the thing a
reader most wants to glance at, and it sits 4000px down.

**Where.** `app.css` mobile block ~1215–1260; `app.js` for any toggle;
`render_compact_slip` for the markup.

**Do.**
- No-JS first: keep the static placement as the fallback. Add an in-page anchor
  in the `mobile-bottom-nav` ("Slip") that already points to `#primary`;
  consider pointing it at the drawer instead.
- With JS: a collapsed bar pinned above the bottom nav showing the badge, leg
  count and price (reuse `drawer-slip-state`), expanding into the drawer with
  `aria-expanded`, `aria-controls`, and focus moved to the drawer heading. Use
  a `hidden` attribute toggle, not `display:none` in inline style.
- Respect `prefers-reduced-motion` for any transition.
- Tokens only; the sheet surface is `--surface-raised`, border `--border`.

**Done when.** JS off: page reads top to bottom, drawer still reachable. JS on:
sheet opens and closes by keyboard, focus is managed, axe-core reports no new
violations, 320px has no horizontal overflow.

---

## Prompt 7: Playwright smoke gate (from the earlier plan, P2 outstanding)

**Problem.** Every visual claim in the last three PRs was verified by hand
with a local script. Nothing in CI opens a browser.

**Where.** New `tests/browser/` or `scripts/smoke.py`; CI in
`.github/workflows/ci.yml`. Fixtures in `browser_fixtures.py` already render
both roles in five states without a database.

**Do.**
- Render each role × state to static HTML with the stylesheet, script and
  fonts rewritten to local paths (the pattern is in
  `docs/frontend-improvement-research.md` and PR #102's description).
- For each page at 1440, 768 and 390: assert `scrollWidth === innerWidth`,
  no console errors, run axe-core (bundled locally, not from a CDN) and fail
  on any violation at `serious` or above.
- Keep it opt-in locally (`SMOKE=1`) and required in CI. Cache the Chromium
  download in CI.

**Done when.** CI runs the gate on PRs; a deliberate 5px overflow in a branch
fails it; the run takes under three minutes.

---

## How to pick these up

Take one prompt per branch. Name branches `<agent>/<short-slug>`. Open the PR
as a draft if the visual check is not done yet. Say in the PR body which
prompt you took and what you changed in the prompt if the codebase had moved.
If a prompt turns out to be wrong about where something lives, fix the prompt
in the same PR.
