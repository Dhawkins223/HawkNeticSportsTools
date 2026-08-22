-- The sports board answers "what is posted right now", but it derived that from
-- the entire collection history: `DISTINCT ON` over every unresolved row of
-- every upcoming game, discarding all but the newest snapshot of each price.
-- The answer stays the size of the slate while the work grows with how long a
-- game has been collected and how often its price moved. Measured at 400,000
-- rows (60,000 unresolved across 60 upcoming games), one board load took 1.6
-- seconds and sorted 60,000 rows through a 10.8 MB external merge to return 120.
--
-- `app.sports_current_quotes` holds exactly the answer: one row per
-- (event, market, selection, line, bookmaker), carrying its most recent
-- observation. The board then reads the slate, not the history.
--
-- It is maintained by a trigger rather than by the collector, because the
-- collector is not the only writer -- imports and backfills reach these tables
-- too -- and a projection that silently diverges from its source is worse than
-- no projection. `sports_board.verify_current_quotes()` re-derives the
-- `DISTINCT ON` answer and reports any disagreement, so drift is detectable
-- rather than assumed impossible.

CREATE TABLE IF NOT EXISTS app.sports_current_quotes (
    id BIGSERIAL PRIMARY KEY,
    prediction_log_id BIGINT NOT NULL
        REFERENCES app.sports_prediction_logs(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    market_type TEXT NOT NULL,
    selection TEXT NOT NULL,
    line NUMERIC(30,12),
    bookmaker TEXT NOT NULL,
    sport TEXT NOT NULL,
    league TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    odds NUMERIC(30,12) NOT NULL,
    odds_format TEXT NOT NULL,
    game_start_time TIMESTAMPTZ NOT NULL,
    odds_timestamp TIMESTAMPTZ NOT NULL,
    api_fetched_at TIMESTAMPTZ NOT NULL,
    prediction_timestamp TIMESTAMPTZ NOT NULL,
    confidence_score NUMERIC(30,12) NOT NULL,
    source_snapshot_hash TEXT NOT NULL,
    run_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    strategy TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- `line` is null for moneylines, and two moneyline quotes from the same book on
-- the same selection are the same quote. NULLS NOT DISTINCT says so, matching
-- how `idx_sports_prediction_exact` already treats the column.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sports_current_quotes_key
    ON app.sports_current_quotes (event_id, market_type, selection, line, bookmaker)
    NULLS NOT DISTINCT;

-- The board's own filter: upcoming games, earliest first.
CREATE INDEX IF NOT EXISTS idx_sports_current_quotes_upcoming
    ON app.sports_current_quotes (game_start_time, event_id);

CREATE INDEX IF NOT EXISTS idx_sports_current_quotes_log
    ON app.sports_current_quotes (prediction_log_id);

-- Freshness is judged on the newest upload across every valid row, settled ones
-- included, so that a day with no upcoming games does not read as a dead
-- collector. That aggregate had no index to use.
CREATE INDEX IF NOT EXISTS idx_sports_prediction_valid_fetched
    ON app.sports_prediction_logs (api_fetched_at DESC)
    WHERE validation_status = 'valid';

-- The promotion lookup below asks for the newest surviving snapshot of one
-- quote key. `idx_sports_prediction_exact` cannot serve it -- that index leads
-- with asset_class, run_id and strategy -- so without this the lookup scans the
-- whole log, and settlement performs one such lookup per quote key. The partial
-- predicate holds it to the live slate rather than the collection history.
CREATE INDEX IF NOT EXISTS idx_sports_prediction_quote_history
    ON app.sports_prediction_logs (
        event_id, market_type, selection, line, bookmaker,
        prediction_timestamp DESC, id DESC)
    WHERE validation_status = 'valid' AND settlement_state = 'unresolved';

-- Losing the newest snapshot of a quote does not mean losing the quote. If an
-- older valid, unresolved snapshot of the same market survives, `DISTINCT ON`
-- still returns it, so the projection has to promote it -- otherwise a rejected
-- or pruned latest observation silently removes a market the board should still
-- show, and the price a bettor sees vanishes rather than reverting.
--
-- Both callers are AFTER triggers, which fire once the statement's changes are
-- visible, so the departing row is already gone or already ineligible and the
-- eligibility filter alone excludes it.
CREATE OR REPLACE FUNCTION app.sports_current_quotes_promote(
    p_event_id TEXT,
    p_market_type TEXT,
    p_selection TEXT,
    p_line NUMERIC,
    p_bookmaker TEXT
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO app.sports_current_quotes (
        prediction_log_id, event_id, market_type, selection, line, bookmaker,
        sport, league, home_team, away_team, odds, odds_format, game_start_time,
        odds_timestamp, api_fetched_at, prediction_timestamp, confidence_score,
        source_snapshot_hash, run_id, model_version, strategy, updated_at
    )
    SELECT id, event_id, market_type, selection, line, bookmaker,
           sport, league, home_team, away_team, odds, odds_format, game_start_time,
           odds_timestamp, api_fetched_at, prediction_timestamp, confidence_score,
           source_snapshot_hash, run_id, model_version, strategy, CURRENT_TIMESTAMP
    FROM app.sports_prediction_logs
    WHERE validation_status = 'valid'
      AND settlement_state = 'unresolved'
      AND event_id = p_event_id
      AND market_type = p_market_type
      AND selection = p_selection
      AND line IS NOT DISTINCT FROM p_line
      AND bookmaker = p_bookmaker
    -- The board's own tie-break, so the promoted row is the one it would pick.
    ORDER BY prediction_timestamp DESC, id DESC
    LIMIT 1
    ON CONFLICT (event_id, market_type, selection, line, bookmaker) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION app.sports_current_quotes_apply() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Only the snapshot that owned the projection can leave a gap, and each path
    -- establishes that differently. On DELETE the foreign key cascades, so the
    -- projection row is usually gone before this runs and our own DELETE matches
    -- nothing; the key's absence is the signal instead. Deleting a log row is
    -- rare, so the extra probe costs nothing that matters.
    IF TG_OP = 'DELETE' THEN
        DELETE FROM app.sports_current_quotes WHERE prediction_log_id = OLD.id;
        IF NOT EXISTS (
            SELECT 1 FROM app.sports_current_quotes
            WHERE event_id = OLD.event_id
              AND market_type = OLD.market_type
              AND selection = OLD.selection
              AND line IS NOT DISTINCT FROM OLD.line
              AND bookmaker = OLD.bookmaker
        ) THEN
            PERFORM app.sports_current_quotes_promote(
                OLD.event_id, OLD.market_type, OLD.selection, OLD.line, OLD.bookmaker);
        END IF;
        RETURN OLD;
    END IF;

    -- A row that is no longer a current quote leaves the projection. Settlement
    -- takes a whole event at once, so its markets leave together and the
    -- promotion finds nothing eligible to promote.
    --
    -- Nothing cascades on this path, so whether our own DELETE matched says
    -- exactly whether this row owned the projection. That guard is not just
    -- tidiness: settlement updates every snapshot of an event, and promoting on
    -- all of them rather than on the handful that own quotes measured three
    -- times the cost for the same result.
    IF NEW.validation_status <> 'valid' OR NEW.settlement_state <> 'unresolved' THEN
        DELETE FROM app.sports_current_quotes WHERE prediction_log_id = NEW.id;
        IF FOUND THEN
            PERFORM app.sports_current_quotes_promote(
                NEW.event_id, NEW.market_type, NEW.selection, NEW.line, NEW.bookmaker);
        END IF;
        RETURN NEW;
    END IF;

    INSERT INTO app.sports_current_quotes (
        prediction_log_id, event_id, market_type, selection, line, bookmaker,
        sport, league, home_team, away_team, odds, odds_format, game_start_time,
        odds_timestamp, api_fetched_at, prediction_timestamp, confidence_score,
        source_snapshot_hash, run_id, model_version, strategy, updated_at
    )
    VALUES (
        NEW.id, NEW.event_id, NEW.market_type, NEW.selection, NEW.line, NEW.bookmaker,
        NEW.sport, NEW.league, NEW.home_team, NEW.away_team, NEW.odds, NEW.odds_format,
        NEW.game_start_time, NEW.odds_timestamp, NEW.api_fetched_at,
        NEW.prediction_timestamp, NEW.confidence_score, NEW.source_snapshot_hash,
        NEW.run_id, NEW.model_version, NEW.strategy, CURRENT_TIMESTAMP
    )
    ON CONFLICT (event_id, market_type, selection, line, bookmaker) DO UPDATE SET
        prediction_log_id = EXCLUDED.prediction_log_id,
        sport = EXCLUDED.sport,
        league = EXCLUDED.league,
        home_team = EXCLUDED.home_team,
        away_team = EXCLUDED.away_team,
        odds = EXCLUDED.odds,
        odds_format = EXCLUDED.odds_format,
        game_start_time = EXCLUDED.game_start_time,
        odds_timestamp = EXCLUDED.odds_timestamp,
        api_fetched_at = EXCLUDED.api_fetched_at,
        prediction_timestamp = EXCLUDED.prediction_timestamp,
        confidence_score = EXCLUDED.confidence_score,
        source_snapshot_hash = EXCLUDED.source_snapshot_hash,
        run_id = EXCLUDED.run_id,
        model_version = EXCLUDED.model_version,
        strategy = EXCLUDED.strategy,
        updated_at = CURRENT_TIMESTAMP
    -- An out-of-order arrival must not overwrite a newer quote. The tie-break on
    -- id matches the board's own ordering.
    WHERE (EXCLUDED.prediction_timestamp, EXCLUDED.prediction_log_id)
        > (app.sports_current_quotes.prediction_timestamp, app.sports_current_quotes.prediction_log_id);

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sports_current_quotes_insert ON app.sports_prediction_logs;
CREATE TRIGGER sports_current_quotes_insert
    AFTER INSERT ON app.sports_prediction_logs
    FOR EACH ROW EXECUTE FUNCTION app.sports_current_quotes_apply();

-- Only an eligibility change matters. The identity and price columns of a
-- logged row are never rewritten -- `sports_clv` updates `closing_line` and
-- `clv`, which the projection does not carry -- so firing on every update would
-- redo the same upsert on every closing-line capture.
DROP TRIGGER IF EXISTS sports_current_quotes_update ON app.sports_prediction_logs;
CREATE TRIGGER sports_current_quotes_update
    AFTER UPDATE ON app.sports_prediction_logs
    FOR EACH ROW
    WHEN (OLD.validation_status IS DISTINCT FROM NEW.validation_status
       OR OLD.settlement_state IS DISTINCT FROM NEW.settlement_state)
    EXECUTE FUNCTION app.sports_current_quotes_apply();

DROP TRIGGER IF EXISTS sports_current_quotes_delete ON app.sports_prediction_logs;
CREATE TRIGGER sports_current_quotes_delete
    AFTER DELETE ON app.sports_prediction_logs
    FOR EACH ROW EXECUTE FUNCTION app.sports_current_quotes_apply();

-- Backfill from whatever is already stored, using the same rule the board used.
INSERT INTO app.sports_current_quotes (
    prediction_log_id, event_id, market_type, selection, line, bookmaker,
    sport, league, home_team, away_team, odds, odds_format, game_start_time,
    odds_timestamp, api_fetched_at, prediction_timestamp, confidence_score,
    source_snapshot_hash, run_id, model_version, strategy
)
SELECT DISTINCT ON (event_id, market_type, selection, line, bookmaker)
       id, event_id, market_type, selection, line, bookmaker,
       sport, league, home_team, away_team, odds, odds_format, game_start_time,
       odds_timestamp, api_fetched_at, prediction_timestamp, confidence_score,
       source_snapshot_hash, run_id, model_version, strategy
FROM app.sports_prediction_logs
WHERE validation_status = 'valid'
  AND settlement_state = 'unresolved'
ORDER BY event_id, market_type, selection, line, bookmaker,
         prediction_timestamp DESC, id DESC
ON CONFLICT (event_id, market_type, selection, line, bookmaker) DO NOTHING;
