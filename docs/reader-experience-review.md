# Reader experience review: research, not wagering

Working note for the `computer/reader-research-framing` branch. It records the
prompts this pass set itself, what the audit found, what changed, what was
deliberately left alone, and the pushback the brief asked for.

Scope is the READER (`read_only`) page. The operator page keeps everything it
had; the only operator-visible change is copy that was reworded for both roles.

## The prompts this pass answered

The brief was open-ended ("create your own prompts and finish it"), so the work
was framed as five questions and each was answered against the rendered page,
not the source.

1. Does the reader page contain any wagering vocabulary, and where?
2. Does any figure on the reader page frame a probability as a recommendation
   to act, or imply a return?
3. When the card shows two "chance" numbers for one slip, can a non-expert
   tell them apart without reading the code?
4. What does the reader see first on a slip card, and is that the finding?
5. Which of the above are copy defects (fixable here) versus product decisions
   that need the owner?

## What the audit found

The page was rendered from the browser fixtures for both roles at 1440px and
390px and read as visible text (tags stripped, scripts removed).

Hard-rule defects on the reader page, before this branch:

| Where | Text | Rule broken |
| --- | --- | --- |
| Slip card metric strip, all three tiers | `Est. $5 Payout` | wagering vocabulary; implied return |
| Right-rail drawer | `Est. $5 payout` | same |
| Tier tiles in "Today's review slips" | `Est. $8.20` | implied return |
| Arithmetic block | `EV on $5.00` | stake framing on the customer page |
| Card packet note | "Manual entry: verify … before placing anything yourself" | frames the page as a step before an action |
| Drawer alert | "…before placing anything yourself" | same |
| Ready summary | "5 legs to enter by hand" | same |

Everything else on the reader page passed: no backend nouns, no fabricated
figures, every probability carries its kind ("Market implied", "95% CI"), and
empty and stale states are honest about what is missing.

## What changed and why

### Money is an operator view

The card had two ways of saying the same thing: the estimate against the
break-even in probability points, and that same gap restated as the expected
value of $5. The second form is the one a bet slip uses. It is also the only
form on the page that needs a stake to exist, so it is the one figure that
cannot be rephrased into research language.

The dollar cells (`Est. $5 payout` on the strip and drawer, `EV on $5.00` in the
arithmetic block, `Est. $x.xx` on the tier tiles) are now behind
`show_dollar_figures`, which `render_dashboard` sets from the same role check
that already gates the operator panels. The operator keeps every one of them.

The reader loses nothing analytical. "Needs to hit", "Estimated to hit" with its
interval, and "Difference" carry the whole finding. Where the tile used to show
a dollar figure the reader now sees `Listed 61.00c`, which is the number they
would actually go and check on Kalshi.

Precedent: [FiveThirtyEight's design write-up](https://fivethirtyeight.com/features/how-we-designed-the-look-of-our-2020-forecast/)
argues a forecast should show "what is known and what is not" and where the
numbers come from, and describes forecasting as "more like predicting the
weather than predicting whether a coin will land on heads or tails". The
[National Weather Service](https://www.weather.gov/ffc/pop) presents
probability of precipitation as a plain likelihood that "simply describes" the
chance, with no framing about what to do with it. The
[Metaculus FAQ](https://www.metaculus.com/faq/) makes the same separation
between a probability and a call to act: an outcome may not be predictable but
"their odds still can be". None of these products put a payout beside the
probability. That is the line between a forecast and a slip.

### The finding leads the card

The card opened on the listed contract's strip (leg floor, listed price,
implied combo) and put the estimate-vs-price block under it. The reader's
question is the second block. The order is now:

1. `Estimate vs. price` (the model's estimate, the break-even, the difference,
   the interval, the leg breakdown)
2. `Listed contract` (the contract's own figures, now under a kicker)
3. Legs by sport

When there is no analysis to show, the listed strip stays first so the card
does not open on a dashed "no analysis" box. The kicker was renamed from
"Slip Arithmetic" to "Estimate vs. price" because a non-expert should be able
to tell what the block is from its title.

### Two "chance" numbers, labelled

The listed strip's `Implied combo` (product of leg market probabilities) and the
arithmetic block's `Estimated to hit` (the model's estimate) are different
numbers for one slip, and sat on the card unlabelled and adjacent. Grouping the
strip under `Listed contract` and leading with the estimate makes the
relationship legible: the listing is context, the estimate is the finding. The
existing note under the arithmetic already says the break-even and the listed
price are different instruments; it was tightened.

### Copy

- "Manual entry: verify … before placing anything yourself" became
  "Research packet: check price, side, and start time against Kalshi before
  relying on any figure here." Same instruction, no implied next step.
- Drawer alert: "Research only. Check every side, price, and start time against
  Kalshi before relying on it."
- Ready summary: "5 legs across ready slips" instead of "5 legs to enter by
  hand". Also pluralises correctly via the existing `leg_label`.

### CSS

Two rules, both from existing tokens, no `!important`:

- `.listed-contract { display: grid; gap: var(--s2); }` so the kicker and
  strip read as one group.
- `.drawer-metrics.is-two-up { grid-template-columns: repeat(2, minmax(0, 1fr)); }`
  because the reader's drawer now holds two figures, and two cells in a
  three-track grid hug the left edge.

### Tests

`ReaderResearchFramingTests` in `tests/test_dashboard_render.py`:

- a whole-word wagering-vocabulary guard over the reader page's visible text in
  the live, empty, stale and error states (`better` and `notebook` do not
  trip it; the old strings do, and a test proves the regex matches them);
- dollar figures present for the operator, absent for the reader;
- the finding still present for both roles;
- reader tiles show `Listed NN.NNc`;
- the drawer declares `is-two-up` and the stylesheet has the rule;
- the estimate block precedes the listed strip on every card, for both roles,
  and a card without an analysis opens on its listing.

Three existing tests that pinned the "Slip Arithmetic" title and one that
pinned "Manual entry" were updated. Full suite: 667 tests, the same 33
Postgres-gated failures as `Master` (no Postgres in the environment this was
written in), `ruff check .` clean. Both roles were re-rendered and
screenshotted at 1440 and 390 with no horizontal overflow and no console
errors on the reader page.

## Honest pushback

**The brief's hard rule is met on the page and broken in the exports.** The
clipboard text (`slip_copy_text`, "$5 payout if right") and the review packet
(`review_packet.py`, "Estimated payout if every leg hits") still use "payout".
The TXT download does too. Those are customer-facing artefacts by any
reasonable reading; they were left alone because the packet has its own
consumers and tests and deserves a deliberate pass, not a find-and-replace
inside a UI PR. The vocabulary guard here checks rendered HTML only. Until the
exports are done, the rule is met in the browser and not in the clipboard.

**"Builder" is sportsbook vocabulary.** The nav says "Kalshi builder", the tab
says "Builder", the panel says "Builder status". "Parlay builder" and "bet
builder" are sportsbook product names. It is not on the brief's banned list and
it is wired into element ids and the operator's JS, so it was not touched here,
but a reader landing on "Builder" is being told this is a place where you
assemble something to submit. "Review" already does that job elsewhere on the
page.

**The hero stat cards are operator counts.** "Games loaded", "Combo contracts",
"Verified today" describe the pipeline's morning, not a finding. They are not
backend vocabulary, so they pass the letter of the rule, but they are the
strongest remaining reason the page can read as an operator dashboard with
holes cut in it. The reader-facing version of this row is probably one card:
how many contracts were checked and when. Owner decision.

**Two probabilities for one slip is a product decision, not a copy one.** The
listed contract's implied chance and the model's estimate are both legitimate
and both belong on the page, but a non-expert will read "59.30%" and "60.1%"
as the tool disagreeing with itself. This branch labels them; it does not
resolve which one the drawer should lead with. Right now the drawer shows the
implied chance and the card headline shows the estimate.

**"low risk" is a judgement, not an estimate.** The badge is computed, but the
word "risk" in a research tool next to a probability is a recommendation in
all but name. "Narrow interval" or "Tight estimate" would say what it measures.
Not changed here because the thresholds and the label live together in the
report builder.

**The 10px micro-labels are still there.** `.metric-strip small` and
`.drawer-metrics small` are 10px uppercase. They pass contrast; they do not
pass comfortably for a reader on a phone. This is on the list from the
previous frontend note and remains open.

## Not done in this environment

`CLAUDE.md` requires the `gstack` toolkit before any work. It is not available
where this branch was written and was not installed. The repo's own checks
(`unittest`, `ruff`, render and screenshot at both widths) were run instead.
`./scripts/local.sh test` needs Postgres/Docker and was not run; the 33 gated
failures are identical to `Master`.
