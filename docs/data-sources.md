# Data Sources

What this platform reads, what it could read, and what each source actually
costs. Sorted by how much of it has been verified rather than by how promising it
sounds.

## Status key

| Status | Meaning |
| --- | --- |
| **Verified** | Fetched and parsed against a real response, with tests over its output |
| **Built, unprobed** | Connector and tests exist; the field mapping follows published documentation and has not met a live response. Run `source-probe <name>` once from a networked machine |
| **In use** | Already wired into a collection path before this document existed |
| **Candidate** | Not built. Listed with what it gives and what it costs |

## Verified

### nflverse — NFL history with closing lines

`connectors/nflverse.py` · `source-probe nflverse` · **free, no key**

`raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv` carries every
NFL game since 1999: final scores, closing moneylines, spreads, totals, rest
days, roof, surface, temperature, wind, referee, and starting quarterbacks.
Measured on 2026-08-20: 7,276 completed games, 5,295 of them with both closing
moneylines (2006 onward), 27 seasons.

This is the only source here large enough to settle a paired test on its own, and
it is what section O of `docs/sports-prediction-research-program.md` was run
against. Two limits are load-bearing:

- **It is not collected evidence.** These rows are a third party's record, not
  something this platform observed with a timestamp and a payload hash of its
  own. They never enter `app.sports_prediction_logs` and cannot reach the board,
  the freshness gates, or any live metric — enforced by where the rows live, not
  by a label: archive games are graded in memory and never reach PostgreSQL, and
  `test_archive_grading_never_writes_to_the_collection_tables` fails if that
  changes. Every report and registry entry also carries
  `evidence_class: reference_data` and `performance_metric_eligible: false`.

  `AGENTS.md` bars historical rows from performance metrics, and this repository's
  own experiment path — *hypothesis → historical reconstruction → leakage audit →
  walk-forward test* — requires them for research. Those are not in tension: a
  walk-forward research score is never a performance metric, and neither a
  collected-source nor an archive run is marked eligible to be one.
- **Its closing lines carry no quote timestamps.** Backlog E-03 — is a stored
  close genuinely the last pre-start price? — is unanswered for this file. The
  dataset's content hash is recorded with every verdict so a later answer can be
  applied to exactly the rows it was computed from.

Licence: the repository is MIT and the data is aggregated from public sources.
Attribution belongs in anything published from it.

## Built, unprobed

Each of these has a connector, a normalizer that refuses what it cannot verify,
and tests over recorded fixtures. Polymarket was revalidated against live public
responses on 2026-08-29; the league probes retain their own explicit live-probe
status. `source-probe` makes one request, runs the real normalizer, and reports
which fields were present, missing, or unparsable — so a shape change is a named
report rather than a stack trace inside a collection cycle.

### Polymarket — a second venue

`connectors/polymarket.py` · `source-probe polymarket` · **free, no key, no account**

`gamma-api.polymarket.com/markets` is a public read-only catalogue of binary
markets, many on the same events Kalshi lists. Kalshi is currently the only
exchange this platform reads, which means its price cannot be checked against
anything: when it moves there is no way to tell whether the world changed or one
order book did. This is the cheapest available answer to backlog E-08.

An exchange price is not a bookmaker price. A sportsbook's two prices sum above
one and the excess is margin that a model such as Shin attributes back; an order
book's two sides sum near one and what they miss by is the spread between resting
orders. The connector normalizes multiplicatively, publishes the
pre-normalization sum, and says which it did — applying a margin model here would
invent a bookmaker's incentive where none exists.

Matching a Polymarket market to a Kalshi market or a game is **not** done: entity
resolution across venues is backlog E-49, and guessing it from a slug's text
would produce confident comparisons of unrelated events. `cross_venue_gaps` takes
the match as an argument.

Migration `0015` and `source_catalog_worker` now persist the public sports
directory, market assets, normalized market observations, and outcome prices to
PostgreSQL with retained raw lineage. This is collection infrastructure, not an
automatic cross-venue match or a validated prediction model.

### MLB StatsAPI and the NHL API — free official results

`connectors/league_feeds.py` · `source-probe mlb`, `source-probe nhl` · **free, no key**

`statsapi.mlb.com/api/v1/schedule` and `api-web.nhle.com/v1/score/{date}` are the
leagues' own systems. The reason to prefer them over a scoreboard scrape is the
status field: they distinguish final from postponed from suspended from in
progress, and a scrape that cannot tell those apart silently converts an
unresolved event into a result. Both normalizers refuse anything not explicitly
final, by name.

Neither carries odds. They extend which leagues the rating can be trained and
graded on; a market baseline still needs a price source.

## In use

| Source | Where | Cost | Notes |
| --- | --- | --- | --- |
| Kalshi public API | `today.py`, `kalshi_ingestion.py` | Free | The platform's primary venue. Public market data needs no key |
| ESPN scoreboard and summary | `sports_research.py` | Free, undocumented | Schedules, scores, and a single provider's odds. Unofficial: no stability guarantee, and it is the failure mode `source-probe` exists to catch |
| The Odds API | `sports_research.py` | Key, free tier ~500 requests/month | The only multi-book odds source wired in. The consensus and line-shopping maths on the board are only as good as the number of books this returns |
| Firecrawl | `connectors/firecrawl.py` | Key, paid tier | Last resort in the retrieval plan. Detects captchas, paywalls, and login walls and reports them as blocked rather than scraping around them |

## Candidates

Free unless noted. Listed with the catch, because every one of these has one.

| Source | Gives | Catch |
| --- | --- | --- |
| nflverse play-by-play releases | Every NFL play since 1999, EPA/WP models included | Hundreds of MB per season; needs a storage plan before it is worth loading |
| `fivethirtyeight/data` NBA Elo | Decades of NBA games with a published Elo for comparison | Archived and no longer updated; useful as a benchmark, not a feed |
| `openfootball/football.json` | Soccer results across many leagues | Results only, no odds; coverage varies by league and season |
| Retrosheet / Chadwick | MLB game logs back to the 19th century | Bulk downloads with their own formats; heavier parsing than the StatsAPI feed |
| balldontlie | NBA schedules, scores, box scores | Now requires a free key and rate-limits hard |
| Pinnacle odds | The sharpest widely-cited closing line | No free public API. Third-party resellers cost real money |
| OddsJam / SportsDataIO / similar | Multi-book odds at useful frequency | Commercial pricing, and the reason the free tier of The Odds API is the current ceiling |

## On scraping

The question "can a bot scrape this for free" has a technical answer and a legal
one, and they differ.

Technically, this repository already has the pieces: `connectors/robots.py`
checks `robots.txt` before a fetch and **fails closed** when it cannot read one,
`connectors/http.py` enforces caching, minimum request intervals, bounded
retries, and a response size cap, and `connectors/firecrawl.py` classifies
captchas, paywalls, and login walls as `blocked` rather than working around them.
The retrieval plan in `SPORTS_RETRIEVAL_PLAN` tries an official API first and
only falls back to scraping.

That ordering is deliberate and should stay. Sportsbook and odds-aggregator terms
of service generally prohibit automated collection, and those sites defend
against it — the practical result of scraping them is not a free data feed but an
intermittent one that fails silently and poisons a metric with gaps. A source
that blocks you half the time is worse than no source, because the half you get
is not a random sample.

The sources worth adding are the ones that publish deliberately: league APIs,
exchange APIs, and public data archives. Every source in the Verified and
Built sections above is one of those, and none of them needed a scraper.

## Adding a source

1. Write the normalizer as a pure function over a payload. It returns rows and an
   explicit count of what it refused, by reason. It never fills in a missing
   field.
2. Test it against recorded fixtures, including the malformed cases.
3. Add it to `source-probe` so one live request reports the field mapping.
4. Decide, explicitly, whether its rows are collected evidence or reference data.
   Reference data does not enter the collection tables and cannot reach the
   board.
5. Record what it cost and what it does not answer, here.
