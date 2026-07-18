ALTER TABLE app.sports_prediction_rejections
    ALTER COLUMN line TYPE NUMERIC(30, 12) USING line::numeric;
