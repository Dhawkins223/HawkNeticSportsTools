-- The public compatibility tables are still the active application contract.
-- Convert legacy floating-point research values before any PostgreSQL-only
-- runtime receives production data.  Source representation remains preserved
-- in raw evidence, while values used for research accounting are exact.
ALTER TABLE edge_results
    ALTER COLUMN model_probability TYPE NUMERIC(18, 12) USING model_probability::NUMERIC,
    ALTER COLUMN entry_price_cents TYPE NUMERIC(18, 8) USING entry_price_cents::NUMERIC,
    ALTER COLUMN fair_price_cents TYPE NUMERIC(18, 8) USING fair_price_cents::NUMERIC,
    ALTER COLUMN expected_value_cents TYPE NUMERIC(18, 8) USING expected_value_cents::NUMERIC;

ALTER TABLE prediction_logs
    ALTER COLUMN confidence_score TYPE NUMERIC(18, 12) USING confidence_score::NUMERIC,
    ALTER COLUMN entry_price_cents TYPE NUMERIC(18, 8) USING entry_price_cents::NUMERIC,
    ALTER COLUMN implied_probability TYPE NUMERIC(18, 12) USING implied_probability::NUMERIC,
    ALTER COLUMN profit_loss_cents TYPE NUMERIC(18, 8) USING profit_loss_cents::NUMERIC;

ALTER TABLE settlement_audit
    ALTER COLUMN previous_profit_loss_cents TYPE NUMERIC(18, 8) USING previous_profit_loss_cents::NUMERIC,
    ALTER COLUMN new_profit_loss_cents TYPE NUMERIC(18, 8) USING new_profit_loss_cents::NUMERIC;

ALTER TABLE crypto_prediction_logs
    ALTER COLUMN entry_price TYPE NUMERIC(24, 12) USING entry_price::NUMERIC,
    ALTER COLUMN open TYPE NUMERIC(24, 12) USING open::NUMERIC,
    ALTER COLUMN high TYPE NUMERIC(24, 12) USING high::NUMERIC,
    ALTER COLUMN low TYPE NUMERIC(24, 12) USING low::NUMERIC,
    ALTER COLUMN close TYPE NUMERIC(24, 12) USING close::NUMERIC,
    ALTER COLUMN volume TYPE NUMERIC(30, 12) USING volume::NUMERIC,
    ALTER COLUMN bid TYPE NUMERIC(24, 12) USING bid::NUMERIC,
    ALTER COLUMN ask TYPE NUMERIC(24, 12) USING ask::NUMERIC,
    ALTER COLUMN mid_price TYPE NUMERIC(24, 12) USING mid_price::NUMERIC,
    ALTER COLUMN spread TYPE NUMERIC(24, 12) USING spread::NUMERIC,
    ALTER COLUMN implied_probability TYPE NUMERIC(18, 12) USING implied_probability::NUMERIC,
    ALTER COLUMN confidence_score TYPE NUMERIC(18, 12) USING confidence_score::NUMERIC,
    ALTER COLUMN settlement_price TYPE NUMERIC(24, 12) USING settlement_price::NUMERIC,
    ALTER COLUMN return_bps TYPE NUMERIC(24, 12) USING return_bps::NUMERIC;

ALTER TABLE sports_prediction_logs
    ALTER COLUMN line TYPE NUMERIC(24, 12) USING line::NUMERIC,
    ALTER COLUMN odds TYPE NUMERIC(24, 12) USING odds::NUMERIC,
    ALTER COLUMN confidence_score TYPE NUMERIC(18, 12) USING confidence_score::NUMERIC,
    ALTER COLUMN closing_line TYPE NUMERIC(24, 12) USING closing_line::NUMERIC,
    ALTER COLUMN clv TYPE NUMERIC(24, 12) USING clv::NUMERIC;

ALTER TABLE sports_prediction_rejections
    ALTER COLUMN line TYPE NUMERIC(24, 12) USING line::NUMERIC;

ALTER TABLE model_evaluations
    ALTER COLUMN brier_score TYPE NUMERIC(18, 12) USING brier_score::NUMERIC,
    ALTER COLUMN log_loss TYPE NUMERIC(18, 12) USING log_loss::NUMERIC,
    ALTER COLUMN calibration_error TYPE NUMERIC(18, 12) USING calibration_error::NUMERIC,
    ALTER COLUMN accuracy TYPE NUMERIC(18, 12) USING accuracy::NUMERIC,
    ALTER COLUMN accuracy_ci_low TYPE NUMERIC(18, 12) USING accuracy_ci_low::NUMERIC,
    ALTER COLUMN accuracy_ci_high TYPE NUMERIC(18, 12) USING accuracy_ci_high::NUMERIC;

ALTER TABLE model_evaluation_predictions
    ALTER COLUMN model_probability TYPE NUMERIC(18, 12) USING model_probability::NUMERIC,
    ALTER COLUMN market_implied_probability TYPE NUMERIC(18, 12) USING market_implied_probability::NUMERIC,
    ALTER COLUMN probability_difference TYPE NUMERIC(18, 12) USING probability_difference::NUMERIC;

ALTER TABLE simulated_executions
    ALTER COLUMN intended_price_cents TYPE NUMERIC(18, 8) USING intended_price_cents::NUMERIC,
    ALTER COLUMN simulated_fill_price_cents TYPE NUMERIC(18, 8) USING simulated_fill_price_cents::NUMERIC,
    ALTER COLUMN fee_estimate_cents TYPE NUMERIC(18, 8) USING fee_estimate_cents::NUMERIC,
    ALTER COLUMN slippage_cents TYPE NUMERIC(18, 8) USING slippage_cents::NUMERIC,
    ALTER COLUMN final_payout_cents TYPE NUMERIC(18, 8) USING final_payout_cents::NUMERIC,
    ALTER COLUMN gross_return_cents TYPE NUMERIC(18, 8) USING gross_return_cents::NUMERIC,
    ALTER COLUMN net_return_cents TYPE NUMERIC(18, 8) USING net_return_cents::NUMERIC;

ALTER TABLE exposure_decisions
    ALTER COLUMN raw_capital_at_risk_cents TYPE NUMERIC(18, 8) USING raw_capital_at_risk_cents::NUMERIC,
    ALTER COLUMN accepted_capital_at_risk_cents TYPE NUMERIC(18, 8) USING accepted_capital_at_risk_cents::NUMERIC;
